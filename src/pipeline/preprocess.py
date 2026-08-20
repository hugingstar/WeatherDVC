import os
import argparse
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path
from src.config import config, get_storage_paths, get_enabled_locations
from src.db import get_records_by_timerange, get_db_connection, release_db_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("pipeline.preprocess")
KST = timezone(timedelta(hours=9))

def compute_discomfort_index(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    """불쾌지수(Discomfort Index / THI) 계산: DI = 9/5*T - 0.55*(1 - RH/100)*(9/5*T - 26) + 32"""
    return (9.0 / 5.0 * temp_c) - (0.55 * (1.0 - rh / 100.0) * (9.0 / 5.0 * temp_c - 26.0)) + 32.0

def compute_wind_chill(temp_c: pd.Series, wind_ms: pd.Series) -> pd.Series:
    """체감온도(Wind Chill Index) 계산 (기온 10도 이하, 풍속 1.3m/s 이상일 때)"""
    wind_kmh = wind_ms * 3.6
    wc = 13.12 + (0.6215 * temp_c) - (11.37 * (wind_kmh ** 0.16)) + (0.3965 * temp_c * (wind_kmh ** 0.16))
    return np.where((temp_c <= 10.0) & (wind_ms >= 1.3), wc, temp_c)

def export_raw_snapshot(target_date: str) -> Path:
    """Export raw records for target_date (YYYY-MM-DD) from DB to data/raw/raw_YYYY-MM-DD.csv"""
    paths = get_storage_paths()
    start_ts = f"{target_date}T00:00:00+09:00"
    end_ts = f"{target_date}T23:59:59+09:00"
    
    records = get_records_by_timerange(start_ts, end_ts)
    raw_file = paths["raw"] / f"raw_{target_date}.csv"
    
    if records:
        df_raw = pd.DataFrame(records)
    else:
        logger.warning(f"No records found for date {target_date}. Fetching latest available or initializing empty.")
        conn = get_db_connection()
        try:
            df_raw = pd.read_sql_query("SELECT * FROM weather_records ORDER BY timestamp DESC LIMIT 500", conn)
        finally:
            release_db_connection(conn)
        if df_raw.empty:
            df_raw = pd.DataFrame(columns=[
                "id", "timestamp", "location_id", "location_name", "latitude", "longitude",
                "temperature", "relative_humidity", "wind_speed", "wind_direction",
                "precipitation", "surface_pressure", "weather_code", "apparent_temperature",
                "collected_at", "source"
            ])
    
    df_raw.to_csv(raw_file, index=False, encoding="utf-8-sig")
    logger.info(f"Raw snapshot exported to {raw_file} (Records: {len(df_raw)})")
    return raw_file

def preprocess_data(raw_file_path: Path):
    paths = get_storage_paths()
    if not raw_file_path.exists():
        logger.error(f"Raw file not found: {raw_file_path}")
        return

    df = pd.read_csv(raw_file_path)
    if df.empty:
        logger.warning("Raw dataset is empty. Creating mock sample structure.")
        return

    # Clean & normalize timestamps
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
    df = df.sort_values(by=["location_id", "timestamp"]).drop_duplicates(subset=["location_id", "timestamp"])

    # Interpolate missing numeric metrics per location
    processed_list = []
    numeric_cols = ["temperature", "relative_humidity", "wind_speed", "wind_direction", "precipitation", "surface_pressure", "apparent_temperature"]

    for loc_id, group in df.groupby("location_id"):
        group = group.copy()
        for col in numeric_cols:
            if col in group.columns:
                group[col] = group[col].interpolate(method="linear").bfill().ffill()
        
        # Calculate derived metrics
        group["discomfort_index"] = compute_discomfort_index(group["temperature"], group["relative_humidity"])
        group["wind_chill"] = compute_wind_chill(group["temperature"], group["wind_speed"])
        group["temp_rolling_15m"] = group["temperature"].rolling(window=15, min_periods=1).mean()
        group["pressure_rolling_15m"] = group["surface_pressure"].rolling(window=15, min_periods=1).mean()
        
        processed_list.append(group)
        
        # Save individual region datasets
        loc_dir = paths["processed"] / "by_region"
        loc_dir.mkdir(parents=True, exist_ok=True)
        group.to_parquet(loc_dir / f"{loc_id}.parquet", index=False)
        group.to_csv(loc_dir / f"{loc_id}.csv", index=False, encoding="utf-8-sig")

    df_all = pd.concat(processed_list, ignore_index=True)
    
    # Save combined datasets for DVC tracking
    combined_parquet = paths["processed"] / "weather_all_regions.parquet"
    combined_csv = paths["processed"] / "weather_all_regions.csv"
    df_all.to_parquet(combined_parquet, index=False)
    df_all.to_csv(combined_csv, index=False, encoding="utf-8-sig")

    logger.info(f"Preprocessing completed. Processed {len(df_all)} records across {df_all['location_id'].nunique()} regions.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess raw weather data for DVC pipeline")
    parser.add_argument("--date", type=str, default=None, help="Target date in YYYY-MM-DD")
    parser.add_argument("--raw-file", type=str, default=None, help="Specific raw file path")
    args = parser.parse_args()

    today_str = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    raw_path = Path(args.raw_file) if args.raw_file else export_raw_snapshot(today_str)
    preprocess_data(raw_path)
