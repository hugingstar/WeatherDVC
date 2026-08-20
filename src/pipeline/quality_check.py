import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.config import config, get_storage_paths

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("pipeline.quality_check")
KST = timezone(timedelta(hours=9))

def evaluate_quality():
    paths = get_storage_paths()
    processed_path = paths["processed"] / "weather_all_regions.parquet"
    if not processed_path.exists():
        csv_fallback = paths["processed"] / "weather_all_regions.csv"
        if not csv_fallback.exists():
            logger.error("No processed dataset found to evaluate.")
            return
        df = pd.read_csv(csv_fallback)
    else:
        df = pd.read_parquet(processed_path)

    if df.empty:
        logger.warning("Processed dataset is empty.")
        return

    thresholds = config.get("quality_thresholds", {})
    expected_daily = thresholds.get("expected_records_per_day", 1440)
    min_comp_ratio = thresholds.get("min_completeness_ratio", 0.95)
    temp_min = thresholds.get("temp_min", -40.0)
    temp_max = thresholds.get("temp_max", 50.0)
    humidity_min = thresholds.get("humidity_min", 0.0)
    humidity_max = thresholds.get("humidity_max", 100.0)
    wind_max = thresholds.get("wind_speed_max", 70.0)
    pressure_min = thresholds.get("pressure_min", 870.0)
    pressure_max = thresholds.get("pressure_max", 1090.0)
    z_thresh = thresholds.get("z_score_threshold", 3.5)

    summary_metrics = {
        "evaluated_at": datetime.now(KST).isoformat(),
        "total_records": int(len(df)),
        "total_regions": int(df["location_id"].nunique()),
        "region_metrics": {},
        "overall_completeness": 0.0,
        "overall_anomalies": 0,
        "overall_quality_score": 100.0,
        "status": "PASS"
    }

    total_expected = expected_daily * df["location_id"].nunique()
    total_anomalies = 0
    scores = []

    for loc_id, group in df.groupby("location_id"):
        loc_name = group["location_name"].iloc[0] if "location_name" in group else loc_id
        count = len(group)
        completeness = min(1.0, count / float(expected_daily)) if expected_daily > 0 else 1.0

        # Physical boundary violations
        temp_violations = int(((group["temperature"] < temp_min) | (group["temperature"] > temp_max)).sum())
        humidity_violations = int(((group["relative_humidity"] < humidity_min) | (group["relative_humidity"] > humidity_max)).sum())
        wind_violations = int((group["wind_speed"] > wind_max).sum())
        pressure_violations = int(((group["surface_pressure"] < pressure_min) | (group["surface_pressure"] > pressure_max)).sum())

        # Statistical Outliers (Z-score)
        temp_std = group["temperature"].std()
        if temp_std > 0.001:
            z_scores = np.abs((group["temperature"] - group["temperature"].mean()) / temp_std)
            temp_z_outliers = int((z_scores > z_thresh).sum())
        else:
            temp_z_outliers = 0

        loc_anomalies = temp_violations + humidity_violations + wind_violations + pressure_violations + temp_z_outliers
        total_anomalies += loc_anomalies

        # Score calculation per region (100 base, deductions for missing & anomalies)
        comp_penalty = max(0.0, (1.0 - completeness) * 50.0)
        anomaly_penalty = min(50.0, (loc_anomalies / max(1, count)) * 100.0)
        region_score = max(0.0, 100.0 - comp_penalty - anomaly_penalty)
        scores.append(region_score)

        region_status = "PASS"
        if completeness < min_comp_ratio or region_score < 80.0:
            region_status = "WARNING" if region_score >= 60.0 else "FAIL"

        loc_metric = {
            "location_id": loc_id,
            "location_name": loc_name,
            "record_count": int(count),
            "completeness_ratio": round(float(completeness), 4),
            "temperature_violations": temp_violations,
            "humidity_violations": humidity_violations,
            "wind_violations": wind_violations,
            "pressure_violations": pressure_violations,
            "temp_z_outliers": temp_z_outliers,
            "total_anomalies": int(loc_anomalies),
            "quality_score": round(float(region_score), 2),
            "status": region_status,
            "stats": {
                "temp_mean": round(float(group["temperature"].mean()), 2),
                "temp_min": round(float(group["temperature"].min()), 2),
                "temp_max": round(float(group["temperature"].max()), 2),
                "humidity_mean": round(float(group["relative_humidity"].mean()), 2),
                "wind_max": round(float(group["wind_speed"].max()), 2)
            }
        }

        summary_metrics["region_metrics"][loc_id] = loc_metric
        # Save individual region metric JSON
        with open(paths["metrics"] / f"quality_{loc_id}.json", "w", encoding="utf-8") as f:
            json.dump(loc_metric, f, indent=2, ensure_ascii=False)

    summary_metrics["overall_completeness"] = round(float(len(df) / total_expected), 4) if total_expected > 0 else 1.0
    summary_metrics["overall_anomalies"] = int(total_anomalies)
    overall_score = np.mean(scores) if scores else 100.0
    summary_metrics["overall_quality_score"] = round(float(overall_score), 2)
    
    if summary_metrics["overall_quality_score"] >= 80.0 and summary_metrics["overall_completeness"] >= min_comp_ratio:
        summary_metrics["status"] = "PASS"
    elif summary_metrics["overall_quality_score"] >= 60.0:
        summary_metrics["status"] = "WARNING"
    else:
        summary_metrics["status"] = "FAIL"

    summary_file = paths["metrics"] / "quality_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_metrics, f, indent=2, ensure_ascii=False)

    logger.info(f"Quality Check completed. Score: {summary_metrics['overall_quality_score']} ({summary_metrics['status']}). Saved to {summary_file}")

if __name__ == "__main__":
    evaluate_quality()
