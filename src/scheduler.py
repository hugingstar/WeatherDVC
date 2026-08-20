import os
import subprocess
import logging
import threading
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import config, ROOT_DIR
from src.pipeline.preprocess import export_raw_snapshot, preprocess_data
from src.pipeline.quality_check import evaluate_quality
from src.pipeline.report_generator import generate_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("weather.scheduler")
KST = timezone(timedelta(hours=9))

scheduler = BackgroundScheduler(timezone="Asia/Seoul")
_pipeline_lock = threading.Lock()

def run_dvc_pipeline(target_date: str = None):
    """Executes the DVC pipeline without blocking the real-time collector."""
    if _pipeline_lock.locked():
        logger.warning("Pipeline run is already in progress. Skipping duplicate execution.")
        return {"status": "busy", "message": "Pipeline execution already running."}

    with _pipeline_lock:
        now_kst = datetime.now(KST)
        date_str = target_date or (now_kst - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"===> Starting Scheduled DVC Pipeline for target date: {date_str} <===")
        
        try:
            # Step 1: Export raw snapshot for the target date
            raw_file = export_raw_snapshot(date_str)
            
            # Step 2: Try running `dvc repro` via subprocess if dvc is initialized, or fallback to direct modules
            dvc_cmd = [
                str(ROOT_DIR / ".venv" / "Scripts" / "dvc.exe") if (ROOT_DIR / ".venv" / "Scripts" / "dvc.exe").exists() else "dvc",
                "repro"
            ]
            
            result = subprocess.run(dvc_cmd, cwd=str(ROOT_DIR), capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"DVC repro succeeded:\n{result.stdout}")
            else:
                logger.warning(f"dvc repro failed or not configured yet ({result.stderr}). Executing direct pipeline modules...")
                preprocess_data(raw_file)
                evaluate_quality()
                generate_report(date_str)

            logger.info(f"===> Scheduled DVC Pipeline Finished Successfully for {date_str} <===")
            return {"status": "success", "date": date_str}
        except Exception as e:
            logger.error(f"Error during DVC pipeline run: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

def start_scheduler():
    cron_expr = config.get("scheduler", {}).get("daily_report_cron", "0 0 * * *")
    # '0 0 * * *' corresponds to hour=0, minute=0
    scheduler.add_job(
        func=run_dvc_pipeline,
        trigger=CronTrigger(hour=0, minute=0, second=0, timezone="Asia/Seoul"),
        id="midnight_dvc_report_job",
        name="Daily Midnight DVC Quality & Report Generator",
        replace_existing=True
    )
    scheduler.start()
    logger.info("BackgroundScheduler started with daily 00:00:00 KST cron job.")

def get_scheduler_status():
    job = scheduler.get_job("midnight_dvc_report_job")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "running": scheduler.running,
        "next_run_time": next_run,
        "pipeline_in_progress": _pipeline_lock.locked()
    }
