import asyncio
import logging
import time
import aiohttp
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from src.config import config, get_enabled_locations
from src.db import insert_weather_records, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("weather.collector")
KST = timezone(timedelta(hours=9))

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

def fetch_weather_sync(location: Dict[str, Any], session: Optional[requests.Session] = None) -> Optional[Dict[str, Any]]:
    sess = session or requests.Session()
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "weather_code"
        ],
        "timezone": "Asia/Seoul"
    }
    timeout = config["collection"].get("timeout_seconds", 10)
    for attempt in range(1, config["collection"].get("retry_attempts", 3) + 1):
        try:
            resp = sess.get(OPEN_METEO_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current", {})
            
            now_kst = datetime.now(KST)
            # Use current reading timestamp or system time
            time_str = current.get("time")
            if time_str:
                try:
                    ts = datetime.fromisoformat(time_str).replace(tzinfo=KST).isoformat()
                except Exception:
                    ts = now_kst.isoformat()
            else:
                ts = now_kst.isoformat()

            record = {
                "timestamp": ts,
                "location_id": location["id"],
                "location_name": location["name"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "temperature": current.get("temperature_2m"),
                "relative_humidity": current.get("relative_humidity_2m"),
                "wind_speed": current.get("wind_speed_10m"),
                "wind_direction": current.get("wind_direction_10m"),
                "precipitation": current.get("precipitation"),
                "surface_pressure": current.get("surface_pressure"),
                "weather_code": current.get("weather_code"),
                "apparent_temperature": current.get("apparent_temperature"),
                "collected_at": now_kst.isoformat(),
                "source": "Open-Meteo"
            }
            return record
        except Exception as e:
            logger.warning(f"[{location['name']}] Attempt {attempt} failed: {e}")
            time.sleep(config["collection"].get("retry_delay_seconds", 2))
    logger.error(f"[{location['name']}] Failed to collect weather data after retries.")
    return None

async def fetch_weather_async(session: aiohttp.ClientSession, location: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    params = {
        "latitude": str(location["latitude"]),
        "longitude": str(location["longitude"]),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,surface_pressure,wind_speed_10m,wind_direction_10m,weather_code",
        "timezone": "Asia/Seoul"
    }
    timeout = aiohttp.ClientTimeout(total=config["collection"].get("timeout_seconds", 10))
    for attempt in range(1, config["collection"].get("retry_attempts", 3) + 1):
        try:
            async with session.get(OPEN_METEO_URL, params=params, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    current = data.get("current", {})
                    now_kst = datetime.now(KST)
                    time_str = current.get("time")
                    if time_str:
                        try:
                            ts = datetime.fromisoformat(time_str).replace(tzinfo=KST).isoformat()
                        except Exception:
                            ts = now_kst.isoformat()
                    else:
                        ts = now_kst.isoformat()

                    return {
                        "timestamp": ts,
                        "location_id": location["id"],
                        "location_name": location["name"],
                        "latitude": location["latitude"],
                        "longitude": location["longitude"],
                        "temperature": current.get("temperature_2m"),
                        "relative_humidity": current.get("relative_humidity_2m"),
                        "wind_speed": current.get("wind_speed_10m"),
                        "wind_direction": current.get("wind_direction_10m"),
                        "precipitation": current.get("precipitation"),
                        "surface_pressure": current.get("surface_pressure"),
                        "weather_code": current.get("weather_code"),
                        "apparent_temperature": current.get("apparent_temperature"),
                        "collected_at": now_kst.isoformat(),
                        "source": "Open-Meteo"
                    }
        except Exception as e:
            logger.warning(f"[{location['name']}] Async attempt {attempt} failed: {e}")
            await asyncio.sleep(config["collection"].get("retry_delay_seconds", 2))
    return None

async def collect_all_locations_async() -> List[Dict[str, Any]]:
    locations = get_enabled_locations()
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_weather_async(session, loc) for loc in locations]
        results = await asyncio.gather(*tasks)
        valid_records = [r for r in results if r is not None]
        if valid_records:
            insert_weather_records(valid_records)
            logger.info(f"Successfully collected and stored {len(valid_records)}/{len(locations)} location records.")
        return valid_records

def collect_once() -> List[Dict[str, Any]]:
    return asyncio.run(collect_all_locations_async())

async def run_collector_loop():
    logger.info("Starting 1-minute real-time weather collector daemon...")
    init_db()
    interval = config["collection"].get("interval_seconds", 60)
    while True:
        start_time = time.time()
        try:
            await collect_all_locations_async()
        except Exception as e:
            logger.error(f"Error in collector loop: {e}", exc_info=True)
        
        elapsed = time.time() - start_time
        sleep_time = max(1.0, interval - elapsed)
        await asyncio.sleep(sleep_time)

if __name__ == "__main__":
    asyncio.run(run_collector_loop())
