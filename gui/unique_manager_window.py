from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s


def _status_color(status: str) -> str:
    return {
        "alive": "#33CC66",
        "possible": "#FFD966",
        "waiting": "#66CCFF",
        "unknown": "#8c8c8c",
    }.get(status, "#d4c5a1")


def _status_text(status: str) -> str:
    return {
        "alive": "Alive",
        "possible": "Can Spawn",
        "waiting": "Waiting",
        "unknown": "No data",
    }.get(status, status)


def _format_countdown(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"


class _KilledBeforeDialog(QDialog):
    timer_selected = pyqtSignal(datetime)

    def __init__(self, unique_name: str, parent=None):
        super().__init__(parent)

        self._active_field = "minutes"
        self._hours_ago = 0
        self._minutes_ago = 10

        self.setWindowTitle(f"Killed Before - {unique_name}")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(360)
        self.setStyleSheet(
            s.ROOT_STYLE
            + s.UNIQUE_DIALOG_STYLE
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        title = QLabel("Set Timer")
        title.setStyleSheet(s.SECTION_TITLE_STYLE)
        layout.addWidget(title)

        subtitle = QLabel(unique_name)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(s.TITLE_STYLE)
        layout.addWidget(subtitle)

        hint_top = QLabel("How long ago was it killed?")
        hint_top.setWordWrap(True)
        hint_top.setStyleSheet(s.INFO_STYLE)
        layout.addWidget(hint_top)

        row = QHBoxLayout()
        row.setSpacing(16)

        row.addWidget(self._build_time_block("Hours", 48, "hours"))
        row.addWidget(self._build_time_block("Minutes", 59, "minutes"))
        row.addStretch()

        wrapper = QHBoxLayout()
        wrapper.addStretch()
        wrapper.addLayout(row)
        wrapper.addStretch()

        layout.addLayout(wrapper)

        hint = QLabel("Click field (Hours/Minutes), then enter digits:")
        hint.setStyleSheet(s.SEARCH_HINT_STYLE)
        layout.addWidget(hint)

        pad = QGridLayout()
        pad.setSpacing(6)

        keys = [
            ("1", 0, 0), ("2", 0, 1), ("3", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("7", 2, 0), ("8", 2, 1), ("9", 2, 2),
            ("C", 3, 0), ("0", 3, 1), ("<", 3, 2),
        ]

        for key, r, c in keys:
            btn = QPushButton(key)
            btn.setObjectName("uniquePadButton")
            btn.setFixedSize(44, 30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
            btn.clicked.connect(lambda _=False, k=key: self._on_pad_key(k))
            pad.addWidget(btn, r, c)

        layout.addLayout(pad)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(26)
        btn_cancel.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
        btn_cancel.clicked.connect(self.reject)

        btn_apply = QPushButton("Apply")
        btn_apply.setFixedHeight(26)
        btn_apply.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
        btn_apply.clicked.connect(self._accept_selection)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_apply)
        layout.addLayout(btn_row)

        self._set_hours(self._hours_ago)
        self._set_minutes(self._minutes_ago)
        self._set_active_field("minutes")

    def _build_time_block(self, title: str, max_value: int, field: str) -> QWidget:
        block = QWidget()
        block.setStyleSheet("background: transparent; border: none;")

        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl = QLabel(title)
        lbl.setFixedWidth(132)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(s.ROW_LABEL_STYLE)
        layout.addWidget(lbl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        minus_btn = self._make_step_button("-")
        plus_btn = self._make_step_button("+")

        edit = self._make_number_edit(max_value)
        edit.mousePressEvent = self._make_edit_click_handler(field)

        if field == "hours":
            self.hours_edit = edit
            self.hours_edit.editingFinished.connect(self._on_hours_edited)
            minus_btn.clicked.connect(lambda: self._set_hours(self._hours_ago - 1))
            plus_btn.clicked.connect(lambda: self._set_hours(self._hours_ago + 1))
        else:
            self.minutes_edit = edit
            self.minutes_edit.editingFinished.connect(self._on_minutes_edited)
            minus_btn.clicked.connect(lambda: self._set_minutes(self._minutes_ago - 1))
            plus_btn.clicked.connect(lambda: self._set_minutes(self._minutes_ago + 1))

        row.addWidget(minus_btn)
        row.addWidget(edit)
        row.addWidget(plus_btn)

        layout.addLayout(row)
        return block

    def _make_edit_click_handler(self, field: str):
        def handler(event):
            self._set_active_field(field)
        return handler

    def _make_number_edit(self, max_value: int) -> QLineEdit:
        edit = QLineEdit()
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setFixedSize(64, 30)
        edit.setMaxLength(2)
        edit.setValidator(QIntValidator(0, max_value, self))
        edit.setReadOnly(True)
        edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        edit.setStyleSheet(s.UNIQUE_INPUT_STYLE)
        return edit

    def _make_step_button(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedSize(28, 30)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(s.UNIQUE_STEP_BUTTON_STYLE)
        return btn

    def _set_active_field(self, field: str):
        self._active_field = field
        self.hours_edit.setStyleSheet(
            s.UNIQUE_ACTIVE_INPUT_STYLE if field == "hours" else s.UNIQUE_INPUT_STYLE
        )
        self.minutes_edit.setStyleSheet(
            s.UNIQUE_ACTIVE_INPUT_STYLE if field == "minutes" else s.UNIQUE_INPUT_STYLE
        )

    def _set_hours(self, value: int):
        self._hours_ago = max(0, min(48, int(value)))
        self.hours_edit.setText(str(self._hours_ago))

    def _set_minutes(self, value: int):
        self._minutes_ago = max(0, min(59, int(value)))
        self.minutes_edit.setText(str(self._minutes_ago))

    def _on_hours_edited(self):
        try:
            self._set_hours(int(self.hours_edit.text() or "0"))
        except ValueError:
            self._set_hours(self._hours_ago)
        self._set_active_field("hours")

    def _on_minutes_edited(self):
        try:
            self._set_minutes(int(self.minutes_edit.text() or "0"))
        except ValueError:
            self._set_minutes(self._minutes_ago)
        self._set_active_field("minutes")

    def _on_pad_key(self, key: str):
        active_edit = self.hours_edit if self._active_field == "hours" else self.minutes_edit
        current = active_edit.text() or "0"

        if key == "C":
            new_val = 0
        elif key == "<":
            trimmed = current[:-1]
            new_val = int(trimmed) if trimmed else 0
        elif key.isdigit():
            merged = ("" if current == "0" else current) + key
            merged = merged[-2:]
            new_val = int(merged) if merged else 0
        else:
            return

        if self._active_field == "hours":
            self._set_hours(new_val)
        else:
            self._set_minutes(new_val)

    def _accept_selection(self):
        total_minutes = max(1, (self._hours_ago * 60) + self._minutes_ago)
        when = datetime.now() - timedelta(minutes=total_minutes)
        self.timer_selected.emit(when)
        self.accept()

class _ConfirmDialog(QDialog):
    confirmed = pyqtSignal()

    def __init__(self, message: str, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Confirm")
        self.setModal(True)
        self.setFixedWidth(300)
        self.setStyleSheet(s.ROOT_STYLE + s.UNIQUE_DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        label = QLabel(message)
        label.setWordWrap(True)
        label.setStyleSheet(s.INFO_STYLE)
        layout.addWidget(label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch()

        yes_btn = QPushButton("Yes")
        yes_btn.setFixedHeight(26)
        yes_btn.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
        yes_btn.clicked.connect(self._accept_confirm)

        no_btn = QPushButton("No")
        no_btn.setFixedHeight(26)
        no_btn.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
        no_btn.clicked.connect(self.reject)

        button_row.addWidget(yes_btn)
        button_row.addWidget(no_btn)
        layout.addLayout(button_row)

    def _accept_confirm(self):
        self.confirmed.emit()
        self.accept()


class UniqueManagerWindow(QWidget):
    timers_changed = pyqtSignal()

    def __init__(self, unique_logic, overlay_parent=None):
        super().__init__()
        self.unique_logic = unique_logic
        self.overlay = overlay_parent
        self._drag_pos = None
        self._row_widgets: dict[str, dict] = {}
        self._definitions = [u for u in self.unique_logic.load_definitions() if u.get("name")]

        self._init_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._refresh_timer.start(1000)

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setWindowTitle("Unique Timers")
        self.setFixedSize(440, 640)
        self.setStyleSheet(s.ROOT_STYLE + s.SCROLLBAR_STYLE + s.UNIQUE_WINDOW_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        title_bar = QFrame()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(s.WINDOW_TITLEBAR_STYLE)

        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(12, 0, 8, 0)

        title_lbl = QLabel("Unique Timers")
        title_lbl.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet(s.WINDOW_TITLE_TEXT_STYLE)
        tb.addWidget(title_lbl)

        tb.addStretch()

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.setFixedHeight(26)
        clear_all_btn.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
        clear_all_btn.clicked.connect(self._on_clear_all_timers)
        tb.addWidget(clear_all_btn)

        tb.addSpacing(6)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(s.WINDOW_CLOSE_BUTTON_STYLE)
        close_btn.clicked.connect(self.close)
        tb.addWidget(close_btn)

        root.addWidget(title_bar)

        title_bar.mousePressEvent = self._start_drag
        title_bar.mouseMoveEvent = self._do_drag

        info = QLabel("Set a kill time to track unique respawns.")
        info.setStyleSheet(s.INFO_STYLE)
        info.setContentsMargins(12, 10, 12, 8)
        root.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._scroll_inner = QWidget()
        self._scroll_inner.setStyleSheet(s.CALENDAR_TRANSPARENT_STYLE)

        self._rows_layout = QVBoxLayout(self._scroll_inner)
        self._rows_layout.setContentsMargins(8, 6, 8, 6)
        self._rows_layout.setSpacing(6)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._scroll_inner)
        root.addWidget(scroll)

        self._build_rows()

    def _timer_map(self) -> dict[str, dict]:
        return {
            item["name"]: item
            for item in self.unique_logic.get_unique_timers(
                respect_overlay_filter=False,
                include_unknown=True,
            )
        }

    def _build_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._row_widgets.clear()
        timers = self._timer_map()

        for unique in self._definitions:
            name = unique["name"]
            data = timers.get(
                name,
                {
                    "name": name,
                    "status": "unknown",
                    "seconds_left": 0,
                },
            )

            card = QFrame()
            card.setObjectName("itemCard")
            card.setStyleSheet(s.CARD_STYLE)

            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            cl.setSpacing(8)

            top = QHBoxLayout()
            top.setSpacing(10)

            left = QVBoxLayout()
            left.setContentsMargins(0, 0, 0, 0)
            left.setSpacing(2)

            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(s.TITLE_STYLE)
            left.addWidget(name_lbl)

            status = data.get("status", "unknown")
            status_lbl = QLabel(_status_text(status))
            status_lbl.setStyleSheet(f"color: {_status_color(status)}; font-size: 9px;")
            left.addWidget(status_lbl)

            top.addLayout(left, 1)

            timer_lbl = QLabel()
            timer_lbl.setMinimumWidth(116)
            timer_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._render_timer(timer_lbl, data)
            top.addWidget(timer_lbl, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            cl.addLayout(top)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(6)

            btn_killed_now = QPushButton("Killed Now")
            btn_killed_now.setFixedHeight(22)
            btn_killed_now.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
            btn_killed_now.clicked.connect(lambda _=False, n=name: self._on_killed_now(n))

            btn_set_timer = QPushButton("Set Timer")
            btn_set_timer.setFixedHeight(22)
            btn_set_timer.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
            btn_set_timer.clicked.connect(lambda _=False, n=name: self._on_set_timer(n))

            btn_remove = QPushButton("Remove")
            btn_remove.setFixedHeight(22)
            btn_remove.setStyleSheet(s.UNIQUE_ACTION_BUTTON_STYLE)
            btn_remove.clicked.connect(lambda _=False, n=name: self._on_remove_timer(n))

            btn_row.addWidget(btn_killed_now)
            btn_row.addWidget(btn_set_timer)
            btn_row.addWidget(btn_remove)
            btn_row.addStretch()

            cl.addLayout(btn_row)

            self._rows_layout.addWidget(card)
            self._row_widgets[name] = {
                "status_lbl": status_lbl,
                "timer_lbl": timer_lbl,
            }

        self._rows_layout.addStretch()

    def _render_timer(self, label: QLabel, data: dict):
        status = data.get("status", "unknown")
        color = _status_color(status)

        if status == "waiting":
            seconds = data.get("seconds_left", data.get("seconds_min", 0))
            label.setText(_format_countdown(seconds))
        elif status == "possible":
            label.setText("Can Spawn!")
        elif status == "alive":
            label.setText("Alive")
        else:
            label.setText("—")

        label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold;")

    def _refresh_all(self):
        timers = self._timer_map()

        for name, widgets in self._row_widgets.items():
            data = timers.get(name, {"status": "unknown", "seconds_left": 0})
            status = data.get("status", "unknown")
            color = _status_color(status)

            widgets["status_lbl"].setText(_status_text(status))
            widgets["status_lbl"].setStyleSheet(f"color: {color}; font-size: 9px;")
            self._render_timer(widgets["timer_lbl"], data)

    def _emit_changed(self):
        self.timers_changed.emit()
        self._refresh_all()

    def _on_killed_now(self, name: str):
        self.unique_logic.update_death(name, source="manual")
        self._emit_changed()

    def _on_set_timer(self, name: str):
        dlg = _KilledBeforeDialog(name, self)

        def _apply(when: datetime):
            if when > datetime.now():
                when = datetime.now()
            self.unique_logic.update_death(name, when=when, source="manual")
            self._emit_changed()

        dlg.timer_selected.connect(_apply)
        dlg.exec()

    def _on_remove_timer(self, name: str):
        self.unique_logic.remove_timer(name)
        self._emit_changed()

    def _on_clear_all_timers(self):
        self.unique_logic.clear_all_timers()
        self._emit_changed()

    def _start_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _do_drag(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)

    def center_on_screen(self):
        screen = self.screen()
        if screen is None:
            return

        geometry = screen.geometry()
        x = (geometry.width() - self.width()) // 2
        y = (geometry.height() - self.height()) // 2
        self.move(x, y)