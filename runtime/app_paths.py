import os
from pathlib import Path


APP_NAME = "LegendsOverlay"
APP_DATA_VERSION = "v2"


def get_appdata_dir() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    path = Path(base) / APP_NAME / APP_DATA_VERSION
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_settings_path() -> Path:
    return get_appdata_dir() / "settings.json"


def get_events_path() -> Path:
    return get_appdata_dir() / "events.json"


def get_uniques_path() -> Path:
    return get_appdata_dir() / "uniques.json"