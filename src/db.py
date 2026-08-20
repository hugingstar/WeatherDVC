import logging
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from src.config import config

logger = logging.getLogger("weather.db")
KST = timezone(timedelta(hours=9))

_pg_pool: Optional[pool.ThreadedConnectionPool] = None

def get_pg_config() -> Dict[str, Any]:
    return config.get("storage", {}).get("postgres", {
        "host": "127.0.0.1",
        "port": 5432,
        "user": "weather_user",
        "password": "weather_password",
        "dbname": "weather_db"
    })

def init_db_pool():
    global _pg_pool
    if _pg_pool is None:
        cfg = get_pg_config()
        try:
            _pg_pool = pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,
                host=cfg.get("host", "127.0.0.1"),
                port=cfg.get("port", 5432),
                user=cfg.get("user", "weather_user"),
                password=cfg.get("password", "weather_password"),
                dbname=cfg.get("dbname", "weather_db"),
                connect_timeout=10
            )
            logger.info("PostgreSQL connection pool initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}")
            raise e

def get_db_connection():
    if _pg_pool is None:
        init_db_pool()
    return _pg_pool.getconn()

def release_db_connection(conn):
    if _pg_pool and conn:
        _pg_pool.putconn(conn)

def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS weather_records (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL,
                location_id VARCHAR(50) NOT NULL,
                location_name VARCHAR(100) NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                temperature DOUBLE PRECISION,
                relative_humidity DOUBLE PRECISION,
                wind_speed DOUBLE PRECISION,
                wind_direction DOUBLE PRECISION,
                precipitation DOUBLE PRECISION,
                surface_pressure DOUBLE PRECISION,
                weather_code INTEGER,
                apparent_temperature DOUBLE PRECISION,
                collected_at TIMESTAMPTZ NOT NULL,
                source VARCHAR(100) DEFAULT 'Open-Meteo'
            );
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_weather_timestamp ON weather_records (timestamp);
            """)
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_weather_location ON weather_records (location_id, timestamp);
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id SERIAL PRIMARY KEY,
                snapshot_date VARCHAR(20) UNIQUE NOT NULL,
                total_records INTEGER NOT NULL,
                export_path TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                status VARCHAR(50) NOT NULL
            );
            """)
            conn.commit()
            logger.info("PostgreSQL database tables and indexes initialized successfully.")
    finally:
        release_db_connection(conn)

def insert_weather_records(records: List[Dict[str, Any]]):
    if not records:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            insert_query = """
            INSERT INTO weather_records (
                timestamp, location_id, location_name, latitude, longitude,
                temperature, relative_humidity, wind_speed, wind_direction,
                precipitation, surface_pressure, weather_code, apparent_temperature,
                collected_at, source
            ) VALUES %s
            """
            values = [
                (
                    r["timestamp"], r["location_id"], r["location_name"], r["latitude"], r["longitude"],
                    r.get("temperature"), r.get("relative_humidity"), r.get("wind_speed"), r.get("wind_direction"),
                    r.get("precipitation"), r.get("surface_pressure"), r.get("weather_code"), r.get("apparent_temperature"),
                    r["collected_at"], r.get("source", "Open-Meteo")
                )
                for r in records
            ]
            execute_values(cursor, insert_query, values)
            conn.commit()
    finally:
        release_db_connection(conn)

def get_latest_weather() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
            SELECT DISTINCT ON (location_id) 
                id, timestamp, location_id, location_name, latitude, longitude,
                temperature, relative_humidity, wind_speed, wind_direction,
                precipitation, surface_pressure, weather_code, apparent_temperature,
                collected_at, source
            FROM weather_records
            ORDER BY location_id, timestamp DESC;
            """)
            rows = cursor.fetchall()
            # Format datetime fields to ISO strings for JSON serialization
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("timestamp"), datetime):
                    d["timestamp"] = d["timestamp"].isoformat()
                if isinstance(d.get("collected_at"), datetime):
                    d["collected_at"] = d["collected_at"].isoformat()
                results.append(d)
            return sorted(results, key=lambda x: x["location_name"])
    finally:
        release_db_connection(conn)

def get_recent_history(location_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if location_id and location_id != "all":
                cursor.execute("""
                SELECT * FROM weather_records
                WHERE location_id = %s
                ORDER BY timestamp DESC
                LIMIT %s;
                """, (location_id, limit))
            else:
                cursor.execute("""
                SELECT * FROM weather_records
                ORDER BY timestamp DESC
                LIMIT %s;
                """, (limit,))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("timestamp"), datetime):
                    d["timestamp"] = d["timestamp"].isoformat()
                if isinstance(d.get("collected_at"), datetime):
                    d["collected_at"] = d["collected_at"].isoformat()
                results.append(d)
            return results
    finally:
        release_db_connection(conn)

def get_records_by_timerange(start_time: str, end_time: str, location_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if location_id and location_id != "all":
                cursor.execute("""
                SELECT * FROM weather_records
                WHERE timestamp >= %s AND timestamp <= %s AND location_id = %s
                ORDER BY timestamp ASC;
                """, (start_time, end_time, location_id))
            else:
                cursor.execute("""
                SELECT * FROM weather_records
                WHERE timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC;
                """, (start_time, end_time))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("timestamp"), datetime):
                    d["timestamp"] = d["timestamp"].isoformat()
                if isinstance(d.get("collected_at"), datetime):
                    d["collected_at"] = d["collected_at"].isoformat()
                results.append(d)
            return results
    finally:
        release_db_connection(conn)

def get_total_record_count() -> int:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM weather_records;")
            return cursor.fetchone()[0]
    finally:
        release_db_connection(conn)
