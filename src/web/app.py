import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import config, get_enabled_locations, get_storage_paths, ROOT_DIR
from src.db import init_db, get_latest_weather, get_recent_history, get_total_record_count
from src.collector import collect_all_locations_async, run_collector_loop
from src.scheduler import start_scheduler, get_scheduler_status, run_dvc_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("weather.web")
KST = timezone(timedelta(hours=9))

collector_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB, Scheduler and Background Collector
    global collector_task
    init_db()
    start_scheduler()
    collector_task = asyncio.create_task(run_collector_loop())
    logger.info("FastAPI Web server, Background Scheduler, and 1-minute Collector started.")
    yield
    # Shutdown
    if collector_task:
        collector_task.cancel()

app = FastAPI(
    title="WeatherMLOps Real-Time Data Pipeline",
    description="1-minute real-time weather collection, DVC versioning, and zero-downtime midnight report dashboard.",
    version="1.0.0",
    lifespan=lifespan
)

# Setup static files and templates
static_dir = ROOT_DIR / "src" / "web" / "static"
templates_dir = ROOT_DIR / "src" / "web" / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    locations = get_enabled_locations()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "locations": locations,
            "app_name": config["app"]["name"]
        }
    )

# --- API Endpoints ---

@app.get("/api/weather/latest")
async def api_get_latest_weather():
    records = get_latest_weather()
    return {"status": "success", "count": len(records), "data": records}

@app.get("/api/weather/history")
async def api_get_history(
    location_id: Optional[str] = Query("all", description="Location ID or 'all'"),
    limit: int = Query(100, ge=1, le=1000)
):
    records = get_recent_history(location_id=location_id, limit=limit)
    return {"status": "success", "count": len(records), "data": records}

@app.get("/api/locations")
async def api_get_locations():
    return {"status": "success", "data": get_enabled_locations()}

@app.get("/api/status")
async def api_get_status():
    total_records = get_total_record_count()
    sched_status = get_scheduler_status()
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "status": "success",
        "current_time_kst": now_kst,
        "total_records": total_records,
        "interval_seconds": config["collection"].get("interval_seconds", 60),
        "scheduler": sched_status,
        "locations_count": len(get_enabled_locations())
    }

@app.post("/api/collector/trigger")
async def api_trigger_collect():
    records = await collect_all_locations_async()
    return {"status": "success", "collected_count": len(records), "timestamp": datetime.now(KST).isoformat()}

@app.post("/api/pipeline/trigger")
async def api_trigger_pipeline(date: Optional[str] = None):
    # Trigger DVC pipeline run in a background thread to prevent UI freezing
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_dvc_pipeline, date)
    return {"status": "success", "result": result}

@app.get("/api/reports")
async def api_list_reports():
    paths = get_storage_paths()
    reports_dir = paths["reports"]
    reports = []
    if reports_dir.exists():
        for file in sorted(reports_dir.glob("*.html"), key=os.path.getmtime, reverse=True):
            if file.name != "latest.html":
                reports.append({
                    "filename": file.name,
                    "size_bytes": file.stat().st_size,
                    "modified_at": datetime.fromtimestamp(file.stat().st_mtime, tz=KST).strftime("%Y-%m-%d %H:%M:%S"),
                    "url": f"/reports/{file.name}"
                })
    return {"status": "success", "reports": reports}

@app.get("/reports/{report_name}")
async def view_report(report_name: str):
    paths = get_storage_paths()
    file_path = paths["reports"] / report_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="text/html")

@app.get("/api/metrics")
async def api_get_quality_metrics():
    paths = get_storage_paths()
    metrics_file = paths["metrics"] / "quality_summary.json"
    if metrics_file.exists():
        import json
        with open(metrics_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"status": "success", "metrics": data}
    return {"status": "not_found", "message": "No quality metrics available yet."}
