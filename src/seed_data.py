import math
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from src.config import get_enabled_locations
from src.db import init_db, insert_weather_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s")
logger = logging.getLogger("weather.seed")
KST = timezone(timedelta(hours=9))

# Base temperature offsets per city in Korea
BASE_TEMPS = {
    "seoul": 24.5,
    "gwangju": 26.2,
    "mokpo": 25.8,
    "busan": 26.8,
    "daegu": 27.5,
    "daejeon": 25.4,
    "incheon": 23.9,
    "jeju": 27.2,
    "gangneung": 24.8
}

def generate_seed_history(hours: int = 24, interval_minutes: int = 1):
    """Generates realistic 1-minute weather history for the past N hours for all regions."""
    init_db()
    locations = get_enabled_locations()
    now = datetime.now(KST)
    start_time = now - timedelta(hours=hours)

    total_steps = int((hours * 60) / interval_minutes)
    logger.info(f"Generating realistic {total_steps} 1-minute data points for {len(locations)} locations...")

    batch_records = []
    
    for step in range(total_steps):
        current_ts = start_time + timedelta(minutes=step * interval_minutes)
        hour_frac = current_ts.hour + current_ts.minute / 60.0
        
        # Diurnal temperature cycle (sinusoidal peak around 14:00, trough around 05:00)
        diurnal_cycle = math.sin((hour_frac - 8.0) * math.pi / 12.0)
        
        for loc in locations:
            loc_id = loc["id"]
            base_t = BASE_TEMPS.get(loc_id, 25.0)
            
            # Temp variation: base + diurnal * 4.5 + slight noise
            temp = base_t + (diurnal_cycle * 4.5) + random.uniform(-0.4, 0.4)
            # Relative humidity inversely correlated with temp
            humidity = max(35.0, min(95.0, 75.0 - (diurnal_cycle * 22.0) + random.uniform(-2.0, 2.0)))
            # Wind speed
            wind_speed = max(0.5, round(2.5 + random.uniform(-1.0, 2.5), 1))
            wind_dir = random.randint(0, 360)
            # Surface pressure
            pressure = round(1012.0 - (temp * 0.15) + random.uniform(-0.5, 0.5), 1)
            # Apparent temperature
            apparent_temp = round(temp + (0.33 * (humidity / 100.0 * 6.105 * math.exp((17.27 * temp) / (237.7 + temp)))) - (0.7 * wind_speed) - 4.0, 1)
            # Precipitation (mostly 0.0 with rare light showers)
            rain = 0.0 if random.random() > 0.03 else round(random.uniform(0.1, 2.5), 1)
            
            record = {
                "timestamp": current_ts.isoformat(),
                "location_id": loc_id,
                "location_name": loc["name"],
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "temperature": round(temp, 1),
                "relative_humidity": round(humidity, 1),
                "wind_speed": wind_speed,
                "wind_direction": wind_dir,
                "precipitation": rain,
                "surface_pressure": pressure,
                "weather_code": 0 if rain == 0 else 51,
                "apparent_temperature": apparent_temp,
                "collected_at": current_ts.isoformat(),
                "source": "Open-Meteo (Historical Sync)"
            }
            batch_records.append(record)
            
            # Insert in chunks of 1,000 to keep memory footprint low
            if len(batch_records) >= 1000:
                insert_weather_records(batch_records)
                batch_records = []

    if batch_records:
        insert_weather_records(batch_records)

    logger.info("Seed data generation and insertion completed successfully!")

if __name__ == "__main__":
    generate_seed_history(hours=24, interval_minutes=1)
