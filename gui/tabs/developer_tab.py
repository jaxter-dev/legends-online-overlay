from PyQt6.QtCore import QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.tabs.shared import style_small_button


class DeveloperTab(QWidget):
    """
    Minimal developer/debug tab.

    MVP:
    - test toast
    - test current voice settings
    - force-show daily banner
    - reset daily check state
    - create debug timer by exact time
    - clear debug timers
    """

    test_toast_requested = pyqtSignal()
    test_voice_requested = pyqtSignal()
    show_daily_banner_requested = pyqtSignal()
    reset_daily_check_requested = pyqtSignal()

    create_debug_timer_requested = pyqtSignal(str, str)
    clear_debug_timers_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet(s.ROOT_STYLE)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)

        layout.addWidget(self._build_notifications_section())
        layout.addWidget(self._build_voice_section())
        layout.addWidget(self._build_daily_check_section())
        layout.addWidget(self._build_debug_timer_section())
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

    def _make_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        style_small_button(btn)
        btn.clicked.connect(slot)
        return btn

    def _build_notifications_section(self) -> QWidget:
        section, layout = self._create_section("Notifications")

        info = QLabel("Developer actions bypass normal runtime checks.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(self._make_button("Test Toast", self.test_toast_requested.emit))
        row.addStretch()
        layout.addLayout(row)

        return section

    def _build_voice_section(self) -> QWidget:
        section, layout = self._create_section("Voice")

        info = QLabel("Uses current voice settings from the Settings tab.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(self._make_button("Test Voice", self.test_voice_requested.emit))
        row.addStretch()
        layout.addLayout(row)

        return section

    def _build_daily_check_section(self) -> QWidget:
        section, layout = self._create_section("Daily Check")

        info = QLabel("Force banner visibility or reset daily claim state.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(
            self._make_button("Show Banner", self.show_daily_banner_requested.emit)
        )
        row.addWidget(
            self._make_button("Reset Daily Check", self.reset_daily_check_requested.emit)
        )
        row.addStretch()
        layout.addLayout(row)

        return section

    def _build_debug_timer_section(self) -> QWidget:
        section, layout = self._create_section("Debug Timer")

        info = QLabel("Create a one-shot debug timer for an exact clock time.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title"))

        self.debug_timer_title_input = QLineEdit()
        self.debug_timer_title_input.setPlaceholderText("Example: Debug CTF")
        title_row.addWidget(self.debug_timer_title_input)

        layout.addLayout(title_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Time"))

        self.debug_timer_time_input = QTimeEdit()
        self.debug_timer_time_input.setDisplayFormat("HH:mm:ss")
        self.debug_timer_time_input.setTime(QTime.currentTime().addSecs(15))
        self.debug_timer_time_input.setCalendarPopup(False)
        time_row.addWidget(self.debug_timer_time_input)

        time_row.addWidget(self._make_button("+30s", lambda: self._add_seconds(30)))
        time_row.addWidget(self._make_button("+1m", lambda: self._add_seconds(60)))
        time_row.addWidget(self._make_button("+5m", lambda: self._add_seconds(300)))
        time_row.addStretch()

        layout.addLayout(time_row)

        actions_row = QHBoxLayout()
        actions_row.addWidget(
            self._make_button("Create Timer", self._emit_create_debug_timer)
        )
        actions_row.addWidget(
            self._make_button("Clear Timers", self.clear_debug_timers_requested.emit)
        )
        actions_row.addStretch()

        layout.addLayout(actions_row)

        return section

    def _add_seconds(self, seconds: int):
        current = self.debug_timer_time_input.time()
        self.debug_timer_time_input.setTime(current.addSecs(int(seconds)))

    def _emit_create_debug_timer(self):
        title = self.debug_timer_title_input.text().strip() or "Debug Timer"
        time_text = self.debug_timer_time_input.time().toString("HH:mm:ss")
        self.create_debug_timer_requested.emit(title, time_text)