import os
import yaml
from pathlib import Path
from typing import List, Dict, Any

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"

def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

config = load_config()

def get_enabled_locations() -> List[Dict[str, Any]]:
    return [loc for loc in config.get("locations", []) if loc.get("enabled", True)]

def get_storage_paths() -> Dict[str, Path]:
    storage = config.get("storage", {})
    paths = {
        "db": ROOT_DIR / storage.get("sqlite_db_path", "data/weather.db"),
        "raw": ROOT_DIR / storage.get("raw_dir", "data/raw"),
        "processed": ROOT_DIR / storage.get("processed_dir", "data/processed"),
        "metrics": ROOT_DIR / storage.get("metrics_dir", "metrics"),
        "reports": ROOT_DIR / storage.get("reports_dir", "reports"),
    }
    # Create directories if they do not exist
    for k, p in paths.items():
        if k == "db":
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)
    return paths
