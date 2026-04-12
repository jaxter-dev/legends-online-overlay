import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime


_SETTINGS_FILE = "settings.json"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _read_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _write_settings(data: dict) -> None:
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _has_module(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _install_package(package_name: str) -> bool:
    try:
        cmd = [sys.executable, "-m", "pip", "install", package_name]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return res.returncode == 0
    except Exception:
        return False


def ensure_runtime_dependencies_first_run() -> dict:
    """
    Best-effort first-run dependency bootstrap.

    Behavior:
    - Runs once (tracked in settings.json: runtime_bootstrap.attempted).
    - In source mode: auto-installs missing Python packages for optional features.
    - In frozen .exe mode: only records missing modules (cannot reliably pip-install into bundle).
    - Persists a report in settings.json: runtime_bootstrap.report.
    """
    settings = _read_settings()
    section = settings.setdefault("runtime_bootstrap", {})
    if bool(section.get("attempted", False)):
        return section.get("report", {}) if isinstance(section.get("report", {}), dict) else {}

    wanted = {
        "pyttsx3": "pyttsx3",
        "pynput": "pynput",
        "keyboard": "keyboard",
    }

    missing = [m for m in wanted.keys() if not _has_module(m)]
    installed = []
    failed = []

    if missing and not _is_frozen():
        for mod in missing:
            pkg = wanted.get(mod, mod)
            ok = _install_package(pkg)
            if ok and _has_module(mod):
                installed.append(mod)
            else:
                failed.append(mod)
    else:
        failed = missing[:]

    report = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "mode": "frozen" if _is_frozen() else "source",
        "missing_before": missing,
        "installed": installed,
        "failed": failed,
    }

    section["attempted"] = True
    section["report"] = report
    _write_settings(settings)
    return report
