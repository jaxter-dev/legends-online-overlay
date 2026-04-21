import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.tabs.notifications_tab import NotificationsTab
from gui.tabs.settings_tab import SettingsTab
from gui.tabs.shared import SETTINGS_STYLE, style_footer_button, style_save_button
from gui.tabs.uniques_tab import UniquesTab
from gui.tabs.developer_tab import DeveloperTab
from runtime.tts_manager import TTSManager
from runtime.app_paths import get_settings_path, get_events_path


class SettingsWindow(QWidget):
    """
    Main settings window.

    Responsibilities:
    - load settings + events data
    - host all settings tabs
    - merge tab outputs into one settings dict
    - save settings.json
    - expose settings_saved signal to controller
    """

    settings_saved = pyqtSignal()

    DEFAULT_SETTINGS: dict[str, Any] = {
        "overlay": {
            "locked": False,
            "position": {"x": 100, "y": 100},
            "max_events_displayed": 5,
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
        },
        "uniques": {
            "enabled_uniques": {},
        },
        "ui": {
            "first_run_welcome_shown": False,
        },
        "time_format": "24h",
    }

    def __init__(self, overlay_parent=None, available_voices: list[str] | None = None):
        super().__init__(overlay_parent)

        self.overlay = overlay_parent
        self.available_voices = available_voices or []
        self.settings_path = get_settings_path()
        self.events_path = get_events_path()

        self._drag_pos = None
        self.tts_manager = TTSManager()

        self.settings_data = self._load_settings()
        self.events_data = self._load_json(self.events_path, default=[])

        self._setup_window()
        self._build_ui()
        self.center_on_screen()

    # ============================================================
    # WINDOW SETUP
    # ============================================================

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Legends Settings")
        self.setFixedWidth(460)
        self.setMinimumHeight(560)
        self.setMaximumHeight(640)
        self.setStyleSheet(SETTINGS_STYLE)

    def center_on_screen(self):
        screen = self.screen()
        if screen is None:
            return

        geometry = screen.geometry()
        x = (geometry.width() - self.width()) // 2
        y = (geometry.height() - self.height()) // 2
        self.move(x, y)

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_tabs())
        root.addWidget(self._build_footer())

    def _build_title_bar(self) -> QFrame:
        title_bar = QFrame()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(s.WINDOW_TITLEBAR_STYLE)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(12, 0, 8, 0)

        title_lbl = QLabel("Settings")
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(s.WINDOW_TITLE_TEXT_STYLE)
        layout.addWidget(title_lbl)

        layout.addStretch()

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(s.WINDOW_CLOSE_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.close)
        layout.addWidget(self.close_btn)

        title_bar.mousePressEvent = self._start_drag
        title_bar.mouseMoveEvent = self._do_drag

        return title_bar

    def _build_tabs(self) -> QTabWidget:
        self.tabs = QTabWidget()

        self.notifications_tab = NotificationsTab(self.settings_data, self.events_data)
        self.uniques_tab = UniquesTab(self.settings_data)
        self.settings_tab = SettingsTab(self.settings_data)

        ENABLE_DEV_TAB = False

        if ENABLE_DEV_TAB:
            self.developer_tab = DeveloperTab()

        self.settings_tab.set_test_callback(self._handle_test_voice)
        self.settings_tab.set_available_voices(self.available_voices)

        if ENABLE_DEV_TAB:
            self.developer_tab.test_voice_requested.connect(self._handle_developer_test_voice)

        self.tabs.addTab(self.notifications_tab, "  🔔  Notifications  ")
        self.tabs.addTab(self.uniques_tab, "  🐉  Uniques  ")
        self.tabs.addTab(self.settings_tab, "  ⚙️  Settings  ")

        if ENABLE_DEV_TAB:
            self.tabs.addTab(self.developer_tab, "  🧪  Developer  ")

        return self.tabs

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(48)
        footer.setStyleSheet(s.WINDOW_FOOTER_STYLE)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)

        version_lbl = QLabel("Version 1.0.0")
        version_lbl.setStyleSheet(s.VERSION_LABEL_STYLE)
        layout.addWidget(version_lbl)

        layout.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        style_footer_button(self.cancel_btn)
        self.cancel_btn.clicked.connect(self.close)

        self.save_btn = QPushButton("Save")
        style_save_button(self.save_btn)
        self.save_btn.clicked.connect(self._on_save)

        layout.addWidget(self.cancel_btn)
        layout.addSpacing(8)
        layout.addWidget(self.save_btn)

        return footer

    # ============================================================
    # LOAD / SAVE
    # ============================================================

    def _load_json(self, path: Path, default: Any) -> Any:
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return default

    def _save_json(self, path: Path, data: Any):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as ex:
            print(f"Failed to save {path}: {ex}")

    def _load_settings(self) -> dict:
        loaded = self._load_json(self.settings_path, default={})
        if not isinstance(loaded, dict):
            loaded = {}

        return self._merge_dicts(self.DEFAULT_SETTINGS, loaded)

    @staticmethod
    def _merge_dicts(base: dict, override: dict) -> dict:
        result = dict(base)

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = SettingsWindow._merge_dicts(result[key], value)
            else:
                result[key] = value

        return result

    # ============================================================
    # SAVE FLOW
    # ============================================================

    def _on_save(self):
        settings_data = self._collect_settings_from_tabs()
        settings_data = self._attach_overlay_position(settings_data)

        self._save_json(self.settings_path, settings_data)
        self.settings_data = settings_data

        self.settings_saved.emit()
        self.close()

    def _collect_settings_from_tabs(self) -> dict:
        settings_data = dict(self.settings_data)

        notif_partial = self.notifications_tab.collect_settings()
        uniques_partial = self.uniques_tab.collect_settings()
        settings_partial = self.settings_tab.collect_settings()

        settings_data = self._merge_dicts(settings_data, settings_partial)

        notif_cfg = self._merge_dicts(
            settings_data.get("notifications", {}),
            notif_partial.get("notifications", {}),
        )

        # SettingsTab je source of truth za toast_enabled.
        settings_tab_notifications = settings_partial.get("notifications", {})
        if "toast_enabled" in settings_tab_notifications:
            notif_cfg["toast_enabled"] = bool(settings_tab_notifications["toast_enabled"])

        settings_data["notifications"] = notif_cfg

        settings_data["uniques"] = self._merge_dicts(
            settings_data.get("uniques", {}),
            uniques_partial.get("uniques", {}),
        )

        return settings_data

    def _attach_overlay_position(self, settings_data: dict) -> dict:
        if self.overlay is None:
            return settings_data

        try:
            pos = self.overlay.pos()
            overlay_cfg = dict(settings_data.get("overlay", {}))
            overlay_cfg["position"] = {
                "x": int(pos.x()),
                "y": int(pos.y()),
            }
            settings_data["overlay"] = overlay_cfg
        except Exception:
            pass

        return settings_data

    # ============================================================
    # WINDOW DRAG
    # ============================================================

    def _start_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _do_drag(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ============================================================
    # TEST VOICE
    # ============================================================

    @staticmethod
    def _normalize_volume(volume: int) -> float:
        return max(0.0, min(1.0, float(volume) / 100.0))

    def _handle_test_voice(self, enabled: bool, voice_name: str, volume: int):
        if not enabled:
            return

        self.tts_manager.speak_async(
            text="Test voice alert. 10 minutes to Capture The Flag.",
            voice_name=voice_name,
            volume=self._normalize_volume(volume),
        )

    def _handle_developer_test_voice(self):
        """
        Developer tab uporablja trenutne UI vrednosti iz Settings taba,
        tudi če še niso shranjene v settings.json.
        """
        settings_partial = self.settings_tab.collect_settings()
        notif_cfg = settings_partial.get("notifications", {})

        self._handle_test_voice(
            enabled=bool(notif_cfg.get("voice_enabled", True)),
            voice_name=str(notif_cfg.get("voice_name", "male")),
            volume=int(notif_cfg.get("volume", 80)),
        )