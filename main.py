import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QCursor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from gui.update_dialog import UpdateDialog
from runtime.update_checker import fetch_latest_update_info, load_current_version
from gui.splash_screen import SplashScreen
from app.state import OverlayRowState, OverlayState
from gui.calendar_window import CalendarWindow
from gui.overlay_window import OverlayWindow
from gui.settings_window import SettingsWindow
from gui.unique_manager_window import UniqueManagerWindow
from runtime.event_engine import EventEngine
from runtime.tts_manager import TTSManager
from runtime.unique_logic import UniqueLogic
from runtime.window_binding import WindowBinding
from runtime.notification_manager import NotificationManager
from runtime.update_checker import fetch_latest_update_info, load_current_version
from runtime.updater import apply_update_and_restart, download_update, get_running_exe_path
from runtime.app_paths import get_settings_path, get_events_path
from runtime.resource_path import resource_path


SERVER_TZ = timezone(timedelta(hours=3))

@dataclass(slots=True)
class DisplayItem:
    """
    Enoten interni model za vse vrstice, ki jih overlay lahko prikaže.

    Zakaj je to uporabno:
    - overlay ne rabi vedeti, ali vrstica prihaja iz eventa ali unique timerja
    - vse lahko sortiramo z isto logiko
    - UI ostane enostaven
    """
    label: str
    value: str
    color: str
    priority: int
    time_key: int
    label_key: str

@dataclass(slots=True)
class DebugAlertItem:
    event_id: str
    occurrence_key: str
    name: str
    status: str
    seconds_until_start: int
    seconds_until_end: int
    source_time: str
    scheduled_time: str
    color: str = "#66CCFF"

class OverlayController:
    """
    Main app controller.

    Responsibilities:
    - load event definitions and settings
    - compute visible overlay rows
    - send state to the overlay UI
    - manage auxiliary windows (settings, calendar, unique manager)
    - process voice alerts
    """

    DEFAULT_SETTINGS: dict[str, Any] = {
        "overlay": {
            "locked": False,
            "position": {"x": 100, "y": 100},
            "max_events_displayed": 5,
        },
        "window_binding": {
            "enabled": False,
            "process_name": "",
            "title_contains": "",
            "hide_when_unfocused": True,
            "hide_when_minimized": True,
        },
        "notifications": {
            "enabled_events": {},
            "voice_enabled": True,
            "voice_name": "male",
            "volume": 80,
            "alert_timing": {
                "ten_minutes": True,
                "five_minutes": True,
                "start": True,
            },
            "toast_enabled": False,
        },
        "uniques": {},
        "daily_check": {
            "enabled": True,
            "last_claim_at": "",
            "dismissed_for_cycle": False,
        },
        "ui": {
            "first_run_welcome_shown": False,
        },
        "time_format": "24h",
    }

    def __init__(self, boot_status_callback=None, show_immediately: bool = True):
        self._boot_status_callback = boot_status_callback
        
        self.events_path = get_events_path()
        self.settings_path = get_settings_path()

        self._ensure_appdata_files()

        self._report_boot_status("Creating overlay window...")

        # Main windows / services
        self.overlay = OverlayWindow()
        self.settings_window: SettingsWindow | None = None
        self.calendar_window: CalendarWindow | None = None
        self.unique_manager_window: UniqueManagerWindow | None = None
        self.tray_icon: QSystemTrayIcon | None = None

        self._report_boot_status("Loading events...")
        self.events = self._load_events()

        self._report_boot_status("Loading settings...")
        self.settings = self._load_settings()
        

        self._report_boot_status("Initializing event engine...")
        self.event_engine = EventEngine(self.events)

        self._report_boot_status("Initializing unique timers...")
        self.unique_logic = UniqueLogic()

        self._report_boot_status("Initializing voice engine...")
        self.tts_manager = TTSManager()

        self._report_boot_status("Loading available voices...")
        self.available_voices = self.tts_manager.list_voices()

        # ✅ Window binding from settings
        cfg = self.settings.get("window_binding", {})
        self.window_binding = WindowBinding(
        enabled=bool(cfg.get("enabled", False)),
        process_name=str(cfg.get("process_name", "")).lower(),
        title_contains=str(cfg.get("title_contains", "")).lower(),
        hide_when_unfocused=bool(cfg.get("hide_when_unfocused", True)),
        hide_when_minimized=bool(cfg.get("hide_when_minimized", True)),
    )

        self._last_bound_state = None
        self._window_poll_divider = 0

        # Runtime alert state
        self._fired_alerts: set[str] = set()
        self._last_item_state: dict[str, dict[str, Any]] = {}
        self._tts_startup_done = False
        self._debug_force_daily_banner = False
        self._debug_timers: list[dict[str, Any]] = []

        # Delayed settings save timer
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_settings)

        # Main overlay refresh timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_state)

        self._report_boot_status("Initializing tray...")
        self._setup_tray_icon()

        self._report_boot_status("Initializing notifications...")
        self.notification_manager = NotificationManager(self.overlay)

        self._report_boot_status("Applying overlay settings...")
        self._apply_overlay_settings_to_window()

        self._report_boot_status("Connecting UI actions...")
        self._connect_overlay_actions()

        self._report_boot_status("Applying cursor...")
        self._apply_global_cursor()

        # Nekateri windowi uporabljajo svež snapshot settings
        self._report_boot_status("Refreshing settings snapshot...")
        self.settings_data = self._load_settings()

        if show_immediately:
            self.start()

    # ============================================================
    # BOOT / SETUP
    # ============================================================

    def start(self):
        self._report_boot_status("Finalizing overlay...")
        self.overlay.show()
        self.timer.start(1000)
        self.update_state()
    
    def _setup_tray_icon(self):
        icon_path = resource_path("assets", "icon.ico")

        self.tray_icon = QSystemTrayIcon(self.overlay)
        self.tray_icon.setIcon(QIcon(str(icon_path)))
        self.tray_icon.setToolTip("Legends Overlay")

        tray_menu = QMenu()

        action_settings = QAction("⚙️ Settings", self.overlay)
        action_settings.triggered.connect(self.open_settings)
        tray_menu.addAction(action_settings)

        action_close = QAction("❌ Close", self.overlay)
        action_close.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(action_close)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _connect_overlay_actions(self):
        """
        OverlayWindow ostane 'UI only', controller pa poveže gumbe z akcijami.
        """
        if hasattr(self.overlay, "btn_settings"):
            self.overlay.btn_settings.clicked.connect(self.open_settings)

        if hasattr(self.overlay, "btn_calendar"):
            self.overlay.btn_calendar.clicked.connect(self.open_calendar)

        if hasattr(self.overlay, "uniques_clicked"):
            self.overlay.uniques_clicked.connect(self.open_unique_manager)

        if hasattr(self.overlay, "daily_check_clicked"):
            self.overlay.daily_check_clicked.connect(self._on_daily_check_clicked)

        self.overlay.position_changed.connect(self._on_overlay_position_changed)

    def _report_boot_status(self, text: str):
        if callable(getattr(self, "_boot_status_callback", None)):
            try:
                self._boot_status_callback(str(text))
            except Exception:
                pass

    def preload_ui(self):
        """
        Preload expensive UI windows during startup,
        so first user click is instant.
        """
        self._report_boot_status("Preloading settings window...")
        if self.settings_window is None:
            self.settings_window = SettingsWindow(
                self.overlay,
                available_voices=self.available_voices,
            )
            self.settings_window.settings_saved.connect(self._on_settings_saved)
            self.settings_window.destroyed.connect(self._on_settings_window_destroyed)

            if hasattr(self.settings_window, "developer_tab"):
                self.settings_window.developer_tab.test_toast_requested.connect(
                    self._debug_test_toast
                )
                self.settings_window.developer_tab.show_daily_banner_requested.connect(
                    self._debug_show_daily_banner
                )
                self.settings_window.developer_tab.reset_daily_check_requested.connect(
                    self._debug_reset_daily_check
                )
                self.settings_window.developer_tab.create_debug_timer_requested.connect(
                    self._debug_create_timer
                )
                if hasattr(self.settings_window.developer_tab, "clear_debug_timers_requested"):
                    self.settings_window.developer_tab.clear_debug_timers_requested.connect(
                        self._debug_clear_timers
                    )

            self.settings_window.hide()

        self._report_boot_status("Preloading calendar window...")
        if self.calendar_window is None:
            self.calendar_window = CalendarWindow(
                event_engine=self.event_engine,
                settings_data=self.settings_data,
                parent=None,
            )
            self.calendar_window.hide()

        self._report_boot_status("Preloading unique manager...")
        if self.unique_manager_window is None:
            self.unique_manager_window = UniqueManagerWindow(
                unique_logic=self.unique_logic,
                overlay_parent=self.overlay,
            )
            self.unique_manager_window.destroyed.connect(self._on_unique_manager_destroyed)
            self.unique_manager_window.timers_changed.connect(self.update_state)
            self.unique_manager_window.hide()

    def _ensure_appdata_files(self):
        """
        Če settings/events še ne obstajajo v AppData,
        jih skopiramo iz bundled data folderja.
        """
        import shutil

        base_dir = Path(__file__).resolve().parent.parent
        data_dir = base_dir / "data"

        if not self.settings_path.exists():
            src = resource_path("data", "settings.json")
            if src.exists():
                shutil.copy(src, self.settings_path)

        if not self.events_path.exists():
            src = resource_path("data", "events.json")
            if src.exists():
                shutil.copy(src, self.events_path)


    # ============================================================
    # LOAD / SAVE
    # ============================================================

    def _load_events(self) -> list[dict]:
        try:
            with self.events_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as ex:
            print(f"Failed to load events.json: {ex}")
        return []

    def _load_settings(self) -> dict:
        try:
            with self.settings_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return self._merge_dicts(
                        json.loads(json.dumps(self.DEFAULT_SETTINGS)),
                        data,
                    )
        except Exception as ex:
            print(f"Failed to load settings.json: {ex}")

        # Vrni kopijo defaultov, da se izognemo nenamernemu deljenju referenc.
        return json.loads(json.dumps(self.DEFAULT_SETTINGS))
    
    def _merge_dicts(self, base: dict, override: dict) -> dict:
        result = dict(base)

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value

        return result

    def _save_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as ex:
            print(f"Failed to save settings.json: {ex}")

    def _reload_settings(self):
        self.settings = self._load_settings()
        self._apply_overlay_settings_to_window()

    # ============================================================
    # OVERLAY SETTINGS / POSITION
    # ============================================================

    def _move_overlay_to_safe_position(self):
        screen = self.overlay.screen() or QApplication.primaryScreen()
        if screen is None:
            return

        geometry = screen.availableGeometry()
        overlay_cfg = self.settings.get("overlay", {})
        pos = overlay_cfg.get("position", {})

        try:
            x = int(pos.get("x", 100))
            y = int(pos.get("y", 100))
        except Exception:
            x, y = 100, 100

        width = self.overlay.width()
        height = self.overlay.height()

        # Če je position manjkajoč ali praktično off-screen, centriraj.
        visible_margin = 40
        is_visible_enough = (
            x + width > geometry.left() + visible_margin
            and x < geometry.right() - visible_margin
            and y + height > geometry.top() + visible_margin
            and y < geometry.bottom() - visible_margin
        )

        if not is_visible_enough:
            x = geometry.x() + (geometry.width() - width) // 2
            y = geometry.y() + (geometry.height() - height) // 2
        else:
            x = max(geometry.left(), min(x, geometry.right() - width))
            y = max(geometry.top(), min(y, geometry.bottom() - height))

        self.overlay.move(x, y)

        overlay_cfg = dict(self.settings.get("overlay", {}))
        overlay_cfg["position"] = {"x": int(x), "y": int(y)}
        self.settings["overlay"] = overlay_cfg
    
    def _apply_overlay_settings_to_window(self):
        overlay_cfg = self.settings.get("overlay", {})
        pos = overlay_cfg.get("position", {})

        self._move_overlay_to_safe_position()

        if hasattr(self.overlay, "set_locked"):
            self.overlay.set_locked(bool(overlay_cfg.get("locked", False)))

    def _on_overlay_position_changed(self, x: int, y: int):
        screen = self.overlay.screen() or QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            x = max(geometry.left(), min(int(x), geometry.right() - self.overlay.width()))
            y = max(geometry.top(), min(int(y), geometry.bottom() - self.overlay.height()))

            self.overlay.move(x, y)

        overlay_cfg = dict(self.settings.get("overlay", {}))
        overlay_cfg["position"] = {"x": int(x), "y": int(y)}
        self.settings["overlay"] = overlay_cfg

        # Debounce save: če user vleče overlay, ne zapisujemo na disk vsak frame.
        self._save_timer.start(300)

    def _get_visible_limit(self) -> int:
        overlay_cfg = self.settings.get("overlay", {})
        limit = int(overlay_cfg.get("max_events_displayed", 5))
        return max(1, min(10, limit))

    # ============================================================
    # BUILD OVERLAY STATE
    # ============================================================

    def build_state(self) -> OverlayState:
        """
        Glavna metoda za overlay:
        1. zberi evente
        2. filtriraj po settings
        3. obdela voice alerts
        4. dodaj unique timerje
        5. vse skupaj sortiraj in pretvori v OverlayRowState
        """
        now = datetime.now()

        event_items = self.event_engine.get_display_items(now=now, max_rows=50)
        event_items = [item for item in event_items if self._is_enabled_for_overlay(item)]

        debug_items = self._build_debug_alert_items(now)

        all_alert_items = list(event_items)
        all_alert_items.extend(debug_items)

        self._process_voice_alerts(all_alert_items)

        display_items = self._build_event_display_items(event_items)
        display_items.extend(self._build_debug_display_items(debug_items))
        display_items.extend(self._build_unique_display_items())

        display_items.sort(key=self._display_item_sort_key)

        rows = [
            OverlayRowState(
                label=item.label,
                value=item.value,
                color=item.color,
            )
            for item in display_items[:self._get_visible_limit()]
        ]

        return OverlayState(
            title="Legends Overlay",
            rows=rows,
        )

    def _build_event_display_items(self, items) -> list[DisplayItem]:
        """
        Pretvori EventEngine iteme v enoten DisplayItem format.

        Priority pravila:
        - active = 0
        - registration = 1
        - vse ostalo = 2
        """
        result: list[DisplayItem] = []

        for item in items:
            if item.status == "active":
                value = f"{self._format_seconds(item.seconds_until_end)}"
                priority = 0
                time_key = 0
            elif item.status == "registration":
                value = f"Reg {self._format_seconds(item.seconds_until_start)}"
                priority = 1
                time_key = item.seconds_until_start
            else:
                value = self._format_seconds(item.seconds_until_start)
                priority = 2
                time_key = item.seconds_until_start

            result.append(
                DisplayItem(
                    label=item.name,
                    value=value,
                    color=item.color,
                    priority=priority,
                    time_key=max(0, int(time_key)),
                    label_key=item.name.lower(),
                )
            )

        return result

    def _build_unique_display_items(self) -> list[DisplayItem]:
        """
        Pretvori unique timerje v enak format kot evente.

        Trenutno namenoma prikazujemo:
        - alive
        - possible

        'waiting' preskočimo, da overlay ostane čist in uporaben.
        """
        result: list[DisplayItem] = []

        uniques = self.unique_logic.get_unique_timers(
            respect_overlay_filter=False,
            include_unknown=False,
        )

        for unique in uniques:
            status = str(unique.get("status", "unknown"))
            name = str(unique.get("name", "Unknown"))
            seconds = max(0, int(unique.get("seconds_left", 0)))

            if status == "unknown":
                continue

            if status == "waiting":
                value = self._format_seconds(seconds)
                priority = 2
                time_key = seconds
                color = "#66CCFF"

            elif status == "possible":
                value = self._format_seconds(seconds)
                priority = 2
                time_key = seconds
                color = "#FFD966"

            elif status == "alive":
                value = "Alive"
                priority = 2
                time_key = 0
                color = "#33CC66"

            else:
                continue

            result.append(
                DisplayItem(
                    label=name,
                    value=value,
                    color=color,
                    priority=priority,
                    time_key=time_key,
                    label_key=name.lower(),
                )
            )

        return result

    @staticmethod
    def _display_item_sort_key(item: DisplayItem) -> tuple[int, int, str]:
        """
        Enoten sort za evente + uniques:
        1. priority
        2. čas
        3. label kot tie-breaker
        """
        return (item.priority, item.time_key, item.label_key)

    def update_state(self):
        self._window_poll_divider += 1

        if self._window_poll_divider >= 2:
            self._window_poll_divider = 0
            self._update_overlay_visibility_from_bound_window()

        # Vedno zgradi state, da alert processing (voice/toast) teče tudi,
        # ko bound window ni v foregroundu.
        state = self.build_state()

        # Overlay vidnost urejamo ločeno od alert processinga.
        if self.window_binding and self._last_bound_state:
            if not self._last_bound_state.found or self._last_bound_state.is_minimized:
                self.overlay.hide()
            elif not self._last_bound_state.is_foreground:
                self.overlay.hide()
            else:
                if not self.overlay.isVisible():
                    self.overlay.show()
                self.overlay.render_state(state)
        else:
            self.overlay.render_state(state)

        if hasattr(self.overlay, "set_daily_banner_visible"):
            self.overlay.set_daily_banner_visible(
                self._debug_force_daily_banner or self._should_show_daily_banner()
            )  

    def _build_debug_alert_items(self, now: datetime) -> list[DebugAlertItem]:
        result: list[DebugAlertItem] = []
        keep_timers: list[dict[str, Any]] = []

        for timer in self._debug_timers:
            trigger_at = timer.get("trigger_at")
            if not isinstance(trigger_at, datetime):
                continue

            seconds_until_start = int((trigger_at - now).total_seconds())
            status = "active" if seconds_until_start <= 0 else "upcoming"

            result.append(
                DebugAlertItem(
                    event_id=str(timer.get("event_id", "debug_timer")),
                    occurrence_key=str(timer.get("occurrence_key", "debug_timer")),
                    name=str(timer.get("name", "Debug Timer")),
                    status=status,
                    seconds_until_start=max(0, seconds_until_start),
                    seconds_until_end=0,
                    source_time=str(timer.get("source_time", "00:00:00")),
                    scheduled_time=str(timer.get("scheduled_time", "00:00:00")),
                    color="#33CC66" if status == "active" else "#66CCFF",
                )
            )

            if seconds_until_start >= -2:
                keep_timers.append(timer)

        self._debug_timers = keep_timers
        return result


    def _build_debug_display_items(self, items: list[DebugAlertItem]) -> list[DisplayItem]:
        result: list[DisplayItem] = []

        for item in items:
            if item.status == "active":
                value = "Debug Active"
                priority = 1
                time_key = 0
                color = "#33CC66"
            else:
                value = self._format_seconds(item.seconds_until_start)
                priority = 2
                time_key = item.seconds_until_start
                color = "#66CCFF"

            result.append(
                DisplayItem(
                    label=f"[DBG] {item.name}",
                    value=value,
                    color=color,
                    priority=priority,
                    time_key=max(0, int(time_key)),
                    label_key=f"debug_{item.name.lower()}",
                )
            )

        return result
            
    # ============================================================
    # FORMAT HELPERS
    # ============================================================

    def _format_seconds(self, total_seconds: int) -> str:
        """
        Vizualni format za overlay:
        - pod 10 min -> MM:SS
        - pod 1 h -> X min
        - nad 1 h -> X h / X h Y min
        """
        total_seconds = max(0, int(total_seconds))

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if total_seconds < 600:
            return f"{minutes:02}:{seconds:02}"

        if total_seconds < 3600:
            return f"{minutes} min"

        if minutes == 0:
            return f"{hours} h"

        return f"{hours} h {minutes} min"

    # ============================================================
    # SETTINGS WINDOW
    # ============================================================

    def open_settings(self):
        self.settings_data = self._load_settings()

        if self.settings_window is None:
            self.settings_window = SettingsWindow(
                self.overlay,
                available_voices=self.available_voices,
            )
            self.settings_window.settings_saved.connect(self._on_settings_saved)
            self.settings_window.destroyed.connect(self._on_settings_window_destroyed)

            if hasattr(self.settings_window, "developer_tab"):
                self.settings_window.developer_tab.test_toast_requested.connect(
                    self._debug_test_toast
                )
                self.settings_window.developer_tab.show_daily_banner_requested.connect(
                    self._debug_show_daily_banner
                )
                self.settings_window.developer_tab.reset_daily_check_requested.connect(
                    self._debug_reset_daily_check
                )
                self.settings_window.developer_tab.create_debug_timer_requested.connect(
                    self._debug_create_timer
                )
                if hasattr(self.settings_window.developer_tab, "clear_debug_timers_requested"):
                    self.settings_window.developer_tab.clear_debug_timers_requested.connect(
                        self._debug_clear_timers
                    )
        else:
            self.settings_window.settings_data = self.settings_data

        self.settings_window.show()
        self.settings_window.raise_()

    def _on_settings_saved(self):
        self._reload_settings()
        self.settings_data = self._load_settings()

        if self.calendar_window is not None:
            self.calendar_window.settings_data = self.settings_data
            self.calendar_window.time_format = self.settings_data.get("time_format", "24h")
            self.calendar_window.refresh()

        self.update_state()

    def _on_settings_window_destroyed(self):
        self.settings_window = None

    # ============================================================
    # DEV TOOLS
    # ============================================================

    def _debug_test_toast(self):
        """
        Developer test toast.
        Bypass-a normalne toast_enabled / focus checke.
        """
        self.notification_manager.show_toast(
            "Legends Overlay",
            "Developer test toast",
            timeout_ms=5000,
        )

    def _debug_show_daily_banner(self):
        """
        Force-prikaže daily banner za debug.
        """
        self._debug_force_daily_banner = True

        if hasattr(self.overlay, "set_daily_banner_visible"):
            self.overlay.set_daily_banner_visible(True)

    def _debug_reset_daily_check(self):
        """
        Resetira daily check state, da se banner lahko ponovno normalno pokaže.
        """
        self._debug_force_daily_banner = False

        daily_cfg = dict(self.settings.get("daily_check", {}))
        daily_cfg["last_claim_at"] = ""
        daily_cfg["dismissed_for_cycle"] = False
        self.settings["daily_check"] = daily_cfg
        self._save_settings()

        self.update_state()

    def _debug_clear_timers(self):
        self._debug_timers.clear()
        print("Cleared debug timers.")
        self.update_state()

    # ============================================================
    # CALENDAR WINDOW
    # ============================================================

    def open_calendar(self):
        self.settings_data = self._load_settings()

        if self.calendar_window is None:
            self.calendar_window = CalendarWindow(
                event_engine=self.event_engine,
                settings_data=self.settings_data,
                parent=None,
            )
        else:
            self.calendar_window.settings_data = self.settings_data
            self.calendar_window.time_format = self.settings_data.get("time_format", "24h")
            self.calendar_window.refresh()

        self.calendar_window.show()
        self.calendar_window.raise_()

        screen = self.calendar_window.screen().geometry()
        x = (screen.width() - self.calendar_window.width()) // 2
        y = (screen.height() - self.calendar_window.height()) // 2
        self.calendar_window.move(x, y)

    # ============================================================
    # UNIQUE MANAGER WINDOW
    # ============================================================

    def open_unique_manager(self):
        if self.unique_logic is None:
            print("Unique logic is not connected yet.")
            return

        if self.unique_manager_window is None:
            self.unique_manager_window = UniqueManagerWindow(
                unique_logic=self.unique_logic,
                overlay_parent=self.overlay,
            )
            self.unique_manager_window.destroyed.connect(self._on_unique_manager_destroyed)
            self.unique_manager_window.timers_changed.connect(self.update_state)

        self.unique_manager_window.show()
        self.unique_manager_window.raise_()
        self.unique_manager_window.center_on_screen()

    def _on_unique_manager_destroyed(self):
        self.unique_manager_window = None

    # ============================================================
    # TRAY
    # ============================================================

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.activateWindow()

    # ============================================================
    # CURSOR
    # ============================================================

    def _apply_global_cursor(self):
        try:
            cursor = self._load_app_cursor()
            if cursor is not None:
                QApplication.setOverrideCursor(cursor)
        except Exception as ex:
            print(f"Failed to apply global cursor: {ex}")

    def _load_app_cursor(self):
        try:
            cursor_path = resource_path("assets", "cursor.cur")
            if not cursor_path.exists():
                return None

            pixmap = QPixmap(str(cursor_path))
            if pixmap.isNull():
                return None

            overlay_cfg = self.settings.get("overlay", {})
            hotspot = overlay_cfg.get("cursor_hotspot", {})

            hx = int(hotspot.get("x", 0))
            hy = int(hotspot.get("y", 0))

            return QCursor(pixmap, hx, hy)
        except Exception as ex:
            print(f"Failed to load cursor: {ex}")
            return None

    # ============================================================
    # EVENT FILTERING / ALERTS
    # ============================================================

    def _build_notification_key(self, item) -> str:
        """
        Enotna konstrukcija ključa za notification settings.

        To logiko imamo na enem mestu, da se ne podvaja
        v _is_alert_enabled_for_item in _is_enabled_for_overlay.
        """
        time_key = getattr(item, "scheduled_time", item.source_time)
        return f"{item.event_id}_{time_key.replace(':', '')}"

    def _is_alert_enabled_for_item(self, item) -> bool:
        notif_cfg = self.settings.get("notifications", {})
        enabled_events = notif_cfg.get("enabled_events", {})
        notif_key = self._build_notification_key(item)
        return bool(enabled_events.get(notif_key, True))

    def _is_enabled_for_overlay(self, item) -> bool:
        notif_cfg = self.settings.get("notifications", {})
        enabled_events = notif_cfg.get("enabled_events", {})
        notif_key = self._build_notification_key(item)
        return bool(enabled_events.get(notif_key, True))

    def _process_voice_alerts(self, items):
        notif_cfg = self.settings.get("notifications", {})
        voice_enabled = bool(notif_cfg.get("voice_enabled", True))
        toast_enabled = bool(notif_cfg.get("toast_enabled", False))

        # Če ni ne glasu ne toastov, sploh nima smisla procesirati alertov.
        if not voice_enabled and not toast_enabled:
            return

        timing = notif_cfg.get("alert_timing", {})
        voice_name = str(notif_cfg.get("voice_name", "default"))
        volume = max(0.0, min(1.0, float(notif_cfg.get("volume", 80)) / 100.0))

        current_state: dict[str, dict[str, Any]] = {}

        for item in items:
            current_state[item.occurrence_key] = {
                "seconds_until_start": int(item.seconds_until_start),
                "status": str(item.status),
            }

            if not self._is_alert_enabled_for_item(item):
                continue

            prev = self._last_item_state.get(item.occurrence_key)

            # Ob prvem ticku samo shranimo stanje.
            # S tem preprečimo, da bi app ob zagonu takoj sprožil alert za vse bližajoče evente.
            if not self._tts_startup_done or prev is None:
                continue

            prev_seconds = int(prev.get("seconds_until_start", 999999))
            prev_status = str(prev.get("status", ""))

            if bool(timing.get("ten_minutes", True)):
                crossed_10m = (
                    prev_seconds > 600
                    and item.seconds_until_start <= 600
                    and item.seconds_until_start > 0
                )
                if crossed_10m:
                    self._fire_alert_once(
                        alert_key=f"{item.occurrence_key}|ten",
                        tts_text=f"{item.name} in 10 minutes" if voice_enabled else "",
                        toast_message=f"{item.name} starts in 10 minutes",
                        voice_name=voice_name,
                        volume=volume,
                    )

            if bool(timing.get("five_minutes", True)):
                crossed_5m = (
                    prev_seconds > 300
                    and item.seconds_until_start <= 300
                    and item.seconds_until_start > 0
                )
                if crossed_5m:
                    self._fire_alert_once(
                        alert_key=f"{item.occurrence_key}|five",
                        tts_text=f"{item.name} in 5 minutes" if voice_enabled else "",
                        toast_message=f"{item.name} starts in 5 minutes",
                        voice_name=voice_name,
                        volume=volume,
                    )

            if bool(timing.get("start", True)):
                became_active = prev_status != "active" and item.status == "active"
                if became_active:
                    self._fire_alert_once(
                        alert_key=f"{item.occurrence_key}|start",
                        tts_text=f"{item.name} has started" if voice_enabled else "",
                        toast_message=f"{item.name} has started",
                        voice_name=voice_name,
                        volume=volume,
                    )

        self._last_item_state = current_state
        self._tts_startup_done = True

    def _fire_alert_once(
        self,
        alert_key: str,
        tts_text: str,
        toast_message: str,
        voice_name: str,
        volume: float,
    ):
        """
        Poskrbi, da se isti alert ne sproži večkrat.
        Sproži:
        - TTS
        - toast (če je omogočen in igra ni v fokusu)
        """
        if alert_key in self._fired_alerts:
            return

        self._fired_alerts.add(alert_key)

        if tts_text.strip():
            self.tts_manager.speak_async(
                text=tts_text,
                voice_name=voice_name,
                volume=volume,
            )

        if self._should_show_toast_notifications():
            self.notification_manager.show_toast(
                "Legends Overlay",
                toast_message,
            )

    # ============================================================
    # VEZANO NA AKTIVNOST OKNA
    # ============================================================

    def _update_overlay_visibility_from_bound_window(self) -> bool:
        if self.window_binding is None:
            return True

        try:
            state = self.window_binding.poll_state()
        except Exception as ex:
            print(f"Window binding poll failed: {ex}")
            return True

        self._last_bound_state = state

        if not state.found:
            return False

        if state.is_minimized:
            return False

        if not state.is_foreground:
            return False

        if not self.overlay.isVisible():
            self.overlay.show()

        return True

    # ============================================================
    # TOAST NOTIFICATIONS
    # ============================================================
    def _should_show_toast_notifications(self) -> bool:
        notif_cfg = self.settings.get("notifications", {})
        if not bool(notif_cfg.get("toast_enabled", False)):
            return False

        if self.window_binding is None or not self.window_binding.enabled:
            return True

        if self._last_bound_state is None:
            return False

        return not self._last_bound_state.is_foreground

    # ============================================================
    # DAILY CHECK
    # ============================================================

    def _can_daily_checkin(self, now: datetime | None = None) -> bool:
        """
        Daily check-in je allowed šele, ko sta od zadnjega claima minila:
        - nov lokalni dan
        - nov server dan

        Oba pogoja morata biti izpolnjena.
        """
        cfg = self.settings.get("daily_check", {})
        if not bool(cfg.get("enabled", True)):
            return False

        raw = str(cfg.get("last_claim_at", "")).strip()
        if not raw:
            return True

        try:
            last_claim = datetime.fromisoformat(raw)
        except Exception:
            return True

        if last_claim.tzinfo is None:
            last_claim = last_claim.astimezone()

        if now is None:
            now = datetime.now().astimezone()
        elif now.tzinfo is None:
            now = now.astimezone()

        last_local_date = last_claim.astimezone().date()
        now_local_date = now.astimezone().date()

        last_server_date = last_claim.astimezone(SERVER_TZ).date()
        now_server_date = now.astimezone(SERVER_TZ).date()

        return (
            now_local_date > last_local_date
            and now_server_date > last_server_date
        )


    def _should_show_daily_banner(self) -> bool:
        cfg = self.settings.get("daily_check", {})
        if not bool(cfg.get("enabled", True)):
            return False

        if not self._can_daily_checkin():
            return False

        return not bool(cfg.get("dismissed_for_cycle", False))


    def _on_daily_check_clicked(self):
        self._debug_force_daily_banner = False

        """
        Klik na daily banner šteje kot claim.

        To pomeni:
        - zapišemo current timestamp
        - resetiramo dismissed flag
        - banner takoj izgine
        """
        daily_cfg = dict(self.settings.get("daily_check", {}))
        daily_cfg["last_claim_at"] = datetime.now().astimezone().isoformat()
        daily_cfg["dismissed_for_cycle"] = False
        self.settings["daily_check"] = daily_cfg
        self._save_settings()

        if hasattr(self.overlay, "set_daily_banner_visible"):
            self.overlay.set_daily_banner_visible(False)


    def _debug_create_timer(self, title: str, time_text: str):
        """
        Ustvari one-shot debug timer za točen čas HH:MM:SS.
        Če je čas danes že mimo, ga planira za jutri.
        """
        now = datetime.now()

        try:
            parts = [int(part) for part in str(time_text).split(":")]
            while len(parts) < 3:
                parts.append(0)

            hour, minute, second = parts[:3]

            trigger_at = now.replace(
                hour=hour,
                minute=minute,
                second=second,
                microsecond=0,
            )

            if trigger_at <= now:
                trigger_at = trigger_at + timedelta(days=1)

        except Exception as ex:
            print(f"Failed to create debug timer from '{time_text}': {ex}")
            return

        safe_title = str(title or "").strip() or "Debug Timer"
        stamp = int(trigger_at.timestamp())

        self._debug_timers.append(
            {
                "event_id": "debug_timer",
                "occurrence_key": f"debug_timer_{stamp}_{len(self._debug_timers)}",
                "name": safe_title,
                "trigger_at": trigger_at,
                "source_time": trigger_at.strftime("%H:%M:%S"),
                "scheduled_time": trigger_at.strftime("%H:%M:%S"),
            }
        )

        seconds_left = max(0, int((trigger_at - now).total_seconds()))
        print(
            f"Created debug timer '{safe_title}' for {trigger_at.strftime('%Y-%m-%d %H:%M:%S')} "
            f"({seconds_left}s from now)."
        )

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    splash = SplashScreen()
    splash.show()
    splash.set_status("Starting Legends Overlay...")

    controller = OverlayController(
        boot_status_callback=splash.set_status,
        show_immediately=False,
    )

    # Hook za naslednji korak: GitHub update check
    splash.set_status("Preloading windows...")
    QApplication.processEvents()
    controller.preload_ui()

    splash.set_status("Checking for updates...")
    QApplication.processEvents()

    current_version = load_current_version()
    update_info = fetch_latest_update_info(current_version)

    if update_info is not None:
        splash.close()
        dialog = UpdateDialog(update_info, parent=None)
        result = dialog.exec()

        if result == UpdateDialog.DialogCode.Accepted:
            if not update_info.download_url:
                print("No downloadable asset found in latest release.")
                splash.show()
                splash.set_status("Launching overlay...")
                QApplication.processEvents()
                controller.start()
                splash.close()
            else:
                dialog.set_updating_state(True)
                QApplication.processEvents()

                temp_dir = Path(tempfile.gettempdir())
                downloaded_exe = temp_dir / "LegendsOverlay_update.exe"

                ok = download_update(update_info.download_url, str(downloaded_exe))
                if ok:
                    current_exe = get_running_exe_path()
                    print(f"Downloaded update to: {downloaded_exe}")
                    print(f"Current exe: {current_exe}")

                    apply_update_and_restart(
                        new_exe_path=str(downloaded_exe),
                        current_exe_path=current_exe,
                    )

                    QApplication.instance().quit()
                    return
                else:
                    dialog.set_updating_state(False)
                    dialog.close()

                    splash.show()
                    splash.set_status("Update download failed. Launching overlay...")
                    QApplication.processEvents()
                    controller.start()
                    splash.close()
        else:
            splash.show()
            splash.set_status("Launching overlay...")
            QApplication.processEvents()
            controller.start()
            splash.close()
    else:
        splash.set_status("Launching overlay...")
        QApplication.processEvents()
        controller.start()
        splash.close()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()