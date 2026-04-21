import json
from datetime import datetime, timedelta
from pathlib import Path

from runtime.app_paths import get_uniques_path, get_settings_path


class UniqueLogic:
    def __init__(self):
        self.definitions_path = get_uniques_path()
        self.settings_path = get_settings_path()

        self._definitions = self._load_definitions()
        self._settings = self._load_settings()

    # =========================
    # LOAD / SAVE
    # =========================
    def _load_definitions(self):
        try:
            with self.definitions_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as ex:
            print(f"Failed to load uniques.json: {ex}")
        return []

    def load_definitions(self):
        return self._definitions

    def _load_settings(self):
        try:
            with self.settings_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

        return {"uniques": {}}

    def _save_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except Exception as ex:
            print(f"Failed to save uniques to settings: {ex}")

    def _get_store(self):
        if "uniques" not in self._settings:
            self._settings["uniques"] = {}
        return self._settings["uniques"]

    # =========================
    # PUBLIC API
    # =========================
    def get_unique_timers(self, respect_overlay_filter=False, include_unknown=True):
        now = datetime.now()
        store = self._get_store()

        result = []

        for u in self._definitions:
            name = u["name"]

            if name not in store:
                if include_unknown:
                    result.append({
                        "name": name,
                        "short_name": u.get("short_name", name),
                        "status": "unknown",
                        "seconds_left": 0,
                    })
                continue

            last_kill = datetime.fromisoformat(store[name]["last_kill"])

            min_spawn = int(u["min_spawn"]) * 60
            max_spawn = int(u["max_spawn"]) * 60

            elapsed = (now - last_kill).total_seconds()

            if elapsed >= max_spawn:
                status = "alive"
                seconds_left = 0

            elif elapsed >= min_spawn:
                status = "possible"
                seconds_left = int(max_spawn - elapsed)

            else:
                status = "waiting"
                seconds_left = int(min_spawn - elapsed)

            result.append({
                "name": name,
                "short_name": u.get("short_name", name),
                "status": status,
                "seconds_left": seconds_left,
            })

        return result

    def update_death(self, name: str, when: datetime = None, source="manual"):
        if when is None:
            when = datetime.now()

        store = self._get_store()
        store[name] = {
            "last_kill": when.isoformat(),
            "source": source,
        }

        self._save_settings()

    def remove_timer(self, name: str):
        store = self._get_store()
        if name in store:
            del store[name]
            self._save_settings()

    def clear_all_timers(self):
        self._settings["uniques"] = {}
        self._save_settings()