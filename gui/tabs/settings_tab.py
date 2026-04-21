from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.tabs.shared import BTN_HEIGHT, style_small_button


class SettingsTab(QWidget):
    """
    General overlay/app settings + global TTS settings.

    Ta tab ureja:
    - overlay lock
    - max visible events
    - time format
    - voice alert settings
    - startup welcome behavior
    """

    MIN_EVENTS = 1
    MAX_EVENTS = 10
    DEFAULT_MAX_EVENTS = 5
    DEFAULT_VOLUME = 80
    VALID_VOICES = {"male", "female"}

    def __init__(self, settings_data: dict | None = None):
        super().__init__()

        self.settings_data = settings_data or {}
        self._max_events_count = self.DEFAULT_MAX_EVENTS
        self._selected_voice = "male"
        self._test_callback = None

        self.setStyleSheet(s.ROOT_STYLE)

        self._build_ui()
        self._load_settings()

    # ============================================================
    # PUBLIC API
    # ============================================================

    def set_test_callback(self, callback):
        """
        Parent window lahko nastavi callback za 'Test Voice'.
        """
        self._test_callback = callback

    def set_available_voices(self, voices: list[str]):
        """
        Ostane zaradi kompatibilnosti s preostalo kodo.

        Trenutno UI podpira samo male / female izbiro,
        zato ta metoda trenutno ne spreminja ničesar.
        """
        _ = voices

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_overlay_position_section())
        layout.addWidget(self._build_show_events_section())
        layout.addWidget(self._build_time_format_section())
        layout.addWidget(self._build_voice_alerts_section())
        layout.addWidget(self._build_toast_section())
        layout.addStretch()

    def _create_section(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        container.setObjectName("sectionCard")
        container.setStyleSheet(s.SECTION_STYLE)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(s.SECTION_TITLE_STYLE)
        layout.addWidget(title_label)

        return container, layout

    def _build_overlay_position_section(self) -> QWidget:
        section, layout = self._create_section("Overlay Position")

        self.lock_cb = QCheckBox("Lock overlay position (drag to move when unlocked)")
        layout.addWidget(self.lock_cb)

        return section

    def _build_show_events_section(self) -> QWidget:
        section, layout = self._create_section("Show Events")

        row = QHBoxLayout()

        label = QLabel("Show up to:")
        label.setMargin(5)
        row.addWidget(label)

        self.max_minus_btn = self._make_step_button("-")
        self.max_minus_btn.clicked.connect(lambda: self._change_max_events(-1))

        self.max_value_lbl = QLabel()
        self.max_value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.max_value_lbl.setFixedSize(42, BTN_HEIGHT)
        self.max_value_lbl.setStyleSheet(s.VALUE_LABEL_STYLE)

        self.max_plus_btn = self._make_step_button("+")
        self.max_plus_btn.clicked.connect(lambda: self._change_max_events(1))

        row.addWidget(self.max_minus_btn)
        row.addWidget(self.max_value_lbl)
        row.addWidget(self.max_plus_btn)
        row.addStretch()

        layout.addLayout(row)
        return section

    def _build_time_format_section(self) -> QWidget:
        section, layout = self._create_section("Time Format")

        row = QHBoxLayout()

        self.fmt_24h = QRadioButton("24h")
        self.fmt_12h = QRadioButton("12h AM/PM")

        self.fmt_group = QButtonGroup(self)
        self.fmt_group.addButton(self.fmt_24h, 0)
        self.fmt_group.addButton(self.fmt_12h, 1)

        row.addWidget(self.fmt_24h)
        row.addWidget(self.fmt_12h)
        row.addStretch()

        layout.addLayout(row)
        return section

    def _build_voice_alerts_section(self) -> QWidget:
        section, layout = self._create_section("Voice Alerts")

        self.chk_voice_enabled = QCheckBox("Enable voice alerts")
        layout.addWidget(self.chk_voice_enabled)

        layout.addLayout(self._build_alert_timing_row())
        layout.addLayout(self._build_volume_row())
        layout.addLayout(self._build_voice_row())
        layout.addLayout(self._build_test_row())

        return section

    def _build_alert_timing_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Timing:"))

        self.chk_ten = QCheckBox("10m")
        self.chk_five = QCheckBox("5m")
        self.chk_start = QCheckBox("Start")

        row.addWidget(self.chk_ten)
        row.addWidget(self.chk_five)
        row.addWidget(self.chk_start)
        row.addStretch()

        return row

    def _build_volume_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Volume"))

        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setStyleSheet(s.SLIDER_STYLE)

        self.lbl_volume = QLabel(f"{self.DEFAULT_VOLUME}%")
        self.lbl_volume.setFixedWidth(40)

        self.slider_volume.valueChanged.connect(
            lambda value: self.lbl_volume.setText(f"{value}%")
        )

        row.addWidget(self.slider_volume)
        row.addWidget(self.lbl_volume)
        return row

    def _build_voice_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Voice"))

        self.btn_voice_male = QPushButton("Male")
        self.btn_voice_female = QPushButton("Female")

        for btn in (self.btn_voice_male, self.btn_voice_female):
            btn.setFixedHeight(BTN_HEIGHT)
            style_small_button(btn)

        self.btn_voice_male.clicked.connect(lambda: self._select_voice("male"))
        self.btn_voice_female.clicked.connect(lambda: self._select_voice("female"))

        row.addWidget(self.btn_voice_male)
        row.addWidget(self.btn_voice_female)
        row.addStretch()

        return row

    def _build_test_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self.btn_test = QPushButton("Test Voice")
        self.btn_test.setFixedWidth(120)
        style_small_button(self.btn_test)
        self.btn_test.clicked.connect(self._on_test_clicked)

        row.addWidget(self.btn_test)
        row.addStretch()

        return row

    def _build_toast_section(self) -> QWidget:
        section, layout = self._create_section("Notifications")

        self.toast_enabled_cb = QCheckBox("Enable toast notifications")
        layout.addWidget(self.toast_enabled_cb)

        info = QLabel("Toasts are shown when alerts fire and the game window is not focused.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        return section

    def _make_step_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(26, BTN_HEIGHT)
        btn.setStyleSheet(s.STEP_BUTTON_STYLE)
        return btn

    # ============================================================
    # LOAD STATE INTO UI
    # ============================================================

    def _load_settings(self):
        overlay_cfg = self.settings_data.get("overlay", {})
        notif_cfg = self.settings_data.get("notifications", {})
        timing_cfg = notif_cfg.get("alert_timing", {})

        self.lock_cb.setChecked(bool(overlay_cfg.get("locked", True)))

        max_events = int(overlay_cfg.get("max_events_displayed", self.DEFAULT_MAX_EVENTS))
        self._set_max_events(max_events)

        time_format = str(self.settings_data.get("time_format", "24h")).strip().lower()
        self.fmt_12h.setChecked(time_format == "12h")
        self.fmt_24h.setChecked(time_format != "12h")

        self.chk_voice_enabled.setChecked(bool(notif_cfg.get("voice_enabled", True)))
        self.chk_ten.setChecked(bool(timing_cfg.get("ten_minutes", True)))
        self.chk_five.setChecked(bool(timing_cfg.get("five_minutes", True)))
        self.chk_start.setChecked(bool(timing_cfg.get("start", True)))

        volume = int(notif_cfg.get("volume", self.DEFAULT_VOLUME))
        self.slider_volume.setValue(max(0, min(100, volume)))

        voice_name = str(notif_cfg.get("voice_name", "male")).strip().lower()
        self._selected_voice = voice_name if voice_name in self.VALID_VOICES else "male"
        self._apply_voice_button_styles()

        # V settings hranimo "first_run_welcome_shown",
        # v UI pa checkbox pomeni obratno: "show welcome window".
        self.toast_enabled_cb.setChecked(bool(notif_cfg.get("toast_enabled", True)))

    # ============================================================
    # MAX EVENTS CONTROL
    # ============================================================

    def _set_max_events(self, value: int):
        self._max_events_count = max(self.MIN_EVENTS, min(self.MAX_EVENTS, int(value)))

        self.max_value_lbl.setText(str(self._max_events_count))
        self.max_minus_btn.setEnabled(self._max_events_count > self.MIN_EVENTS)
        self.max_plus_btn.setEnabled(self._max_events_count < self.MAX_EVENTS)

    def _change_max_events(self, delta: int):
        self._set_max_events(self._max_events_count + int(delta))

    # ============================================================
    # VOICE UI
    # ============================================================

    def _select_voice(self, voice_name: str):
        if voice_name not in self.VALID_VOICES:
            return

        self._selected_voice = voice_name
        self._apply_voice_button_styles()

    def _apply_voice_button_styles(self):
        self.btn_voice_male.setStyleSheet(
            s.TOGGLE_ON_STYLE if self._selected_voice == "male" else s.TOGGLE_OFF_STYLE
        )
        self.btn_voice_female.setStyleSheet(
            s.TOGGLE_ON_STYLE if self._selected_voice == "female" else s.TOGGLE_OFF_STYLE
        )

    def _on_test_clicked(self):
        if callable(self._test_callback):
            self._test_callback(
                enabled=self.chk_voice_enabled.isChecked(),
                voice_name=self._selected_voice,
                volume=self.slider_volume.value(),
            )

    # ============================================================
    # EXPORT SETTINGS
    # ============================================================

    def collect_settings(self) -> dict:
        """
        Vrne full settings dict za ta tab.

        Pomembni contracti:
        - overlay.max_events_displayed
        - notifications.voice_enabled / voice_name / volume
        - notifications.alert_timing
        - time_format
        - ui.first_run_welcome_shown
        """
        settings_data = dict(self.settings_data)

        overlay_cfg = dict(settings_data.get("overlay", {}))
        overlay_cfg["locked"] = self.lock_cb.isChecked()
        overlay_cfg["max_events_displayed"] = self._max_events_count
        settings_data["overlay"] = overlay_cfg

        settings_data["time_format"] = "12h" if self.fmt_12h.isChecked() else "24h"

        notif_cfg = dict(settings_data.get("notifications", {}))
        notif_cfg["voice_enabled"] = self.chk_voice_enabled.isChecked()
        notif_cfg["voice_name"] = self._selected_voice or "male"
        notif_cfg["volume"] = int(self.slider_volume.value())
        notif_cfg["toast_enabled"] = self.toast_enabled_cb.isChecked()
        notif_cfg["alert_timing"] = {
            "ten_minutes": self.chk_ten.isChecked(),
            "five_minutes": self.chk_five.isChecked(),
            "start": self.chk_start.isChecked(),
        }
        settings_data["notifications"] = notif_cfg

        return settings_data