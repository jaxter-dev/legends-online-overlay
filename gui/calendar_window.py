from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.event_detail_popup import EventDetailPopup
from runtime.event_engine import EventEngine, EventOccurrence


SERVER_TZ = timezone(timedelta(hours=3))


class ClickableEventLabel(QPushButton):
    """
    Lahka clickable vrstica za event v koledarju.

    Namesto posebnega custom widgeta uporabimo QPushButton,
    ker je:
    - lahek
    - enostaven za style-at
    - že podpira click signal
    """

    def __init__(self, occurrence: EventOccurrence, text: str, on_click, parent=None):
        super().__init__(text, parent)

        self.occurrence = occurrence
        self._on_click = on_click

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.clicked.connect(self._handle_click)

    def _handle_click(self):
        if callable(self._on_click):
            self._on_click(self.occurrence)


class CalendarWindow(QWidget):
    """
    Weekly event calendar window.

    Odgovornosti:
    - prikaže 7-dnevni pregled eventov
    - omogoča klik na event za detail popup
    - prikazuje čase v userjevem izbranem formatu
    """

    DAYS = 7
    CENTER_INDEX = 3
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 600

    def __init__(self, event_engine: EventEngine, settings_data=None, parent=None):
        super().__init__(parent)

        self.event_engine = event_engine
        self.settings_data = settings_data or {}
        self.time_format = self.settings_data.get("time_format", "24h")

        self._drag_pos = None
        self.detail_popup: EventDetailPopup | None = None

        self.setStyleSheet(s.CALENDAR_WINDOW_ROOT_STYLE)

        self._setup_window()
        self._build_ui()
        self.refresh()
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
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())

        self.info_lbl = QLabel(
            "Click an event for details. All times are shown in your local timezone."
        )
        self.info_lbl.setStyleSheet(s.INFO_STYLE)
        root.addWidget(self.info_lbl)

        self.header_row, self.header_layout, self.header_scroll_spacer = self._build_header_row(34)
        root.addWidget(self.header_row)

        self.underline_row, self.header_underline_layout, self.underline_scroll_spacer = self._build_header_row(2)
        root.addWidget(self.underline_row)

        self.week_scroll = self._build_scroll_area()
        root.addWidget(self.week_scroll, 1)

        self.detail_popup = EventDetailPopup(self)
        self.detail_popup.hide()

        self._update_scrollbar_spacer()

    def _build_title_bar(self) -> QFrame:
        title_bar = QFrame()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(s.WINDOW_TITLEBAR_STYLE)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(0)

        title = QLabel("Weekly Event Calendar")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet(s.WINDOW_TITLE_TEXT_STYLE)
        layout.addWidget(title)

        layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setStyleSheet(s.WINDOW_CLOSE_BUTTON_STYLE)
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        title_bar.mousePressEvent = self._start_drag
        title_bar.mouseMoveEvent = self._do_drag

        return title_bar

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setStyleSheet(s.SCROLLBAR_STYLE)
        scroll.setContentsMargins(0, 0, 0, 0)
        scroll.viewport().setContentsMargins(0, 0, 0, 0)

        self.events_container = QWidget()
        self.events_container.setStyleSheet(s.CALENDAR_TRANSPARENT_STYLE)

        self.events_layout = QHBoxLayout(self.events_container)
        self.events_layout.setContentsMargins(0, 0, 0, 0)
        self.events_layout.setSpacing(0)

        scroll.setWidget(self.events_container)
        return scroll

    def _build_header_row(self, height: int):
        """
        Header row + spacer za poravnavo s scroll area scrollbarjem.
        """
        row = QWidget()

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        content = QWidget()
        content.setFixedHeight(height)

        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        spacer = QWidget()
        spacer.setFixedWidth(self._scrollbar_width())
        spacer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        spacer.setStyleSheet(s.CALENDAR_TRANSPARENT_STYLE)

        row_layout.addWidget(content, 1)
        row_layout.addWidget(spacer, 0)

        return row, content_layout, spacer

    # ============================================================
    # REFRESH / CONTENT BUILD
    # ============================================================

    def refresh(self):
        """
        Rebuild trenutni tedenski prikaz.

        Ker je število dni majhno (7) in število eventov omejeno,
        je full rebuild tukaj povsem sprejemljiv in bolj enostaven za vzdrževanje.
        """
        self._clear_layout(self.header_layout)
        self._clear_layout(self.header_underline_layout)
        self._clear_layout(self.events_layout)

        now = datetime.now().astimezone().replace(tzinfo=None)
        grouped = self.event_engine.get_week_occurrences(
            now,
            days=self.DAYS,
            center_index=self.CENTER_INDEX,
        )
        start_date = now.date() - timedelta(days=self.CENTER_INDEX)

        for index in range(self.DAYS):
            day_date = start_date + timedelta(days=index)
            is_today = day_date == now.date()

            self.header_layout.addWidget(self._build_day_header(day_date, is_today), 1)
            self.header_underline_layout.addWidget(self._build_day_underline(is_today), 1)
            self.events_layout.addWidget(
                self._build_day_column(
                    items=grouped[index],
                    now=now,
                    is_today=is_today,
                ),
                1,
            )

        self._update_scrollbar_spacer()

    def _build_day_header(self, day_date, is_today: bool) -> QLabel:
        header = QLabel(day_date.strftime("%a %b %d"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFixedHeight(32)
        header.setStyleSheet(
            s.CALENDAR_DAY_HEADER_TODAY_STYLE if is_today else s.CALENDAR_DAY_HEADER_STYLE
        )
        return header

    def _build_day_underline(self, is_today: bool) -> QFrame:
        underline = QFrame()
        underline.setFixedHeight(2)
        underline.setStyleSheet(
            s.CALENDAR_DAY_UNDERLINE_TODAY_STYLE if is_today else s.CALENDAR_DAY_UNDERLINE_STYLE
        )
        return underline

    def _build_day_column(
        self,
        items: list[EventOccurrence],
        now: datetime,
        is_today: bool,
    ) -> QFrame:
        frame = QFrame()
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setStyleSheet(
            s.CALENDAR_DAY_COLUMN_TODAY_STYLE if is_today else s.CALENDAR_DAY_COLUMN_NORMAL_STYLE
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for occurrence in items:
            layout.addWidget(self._build_event_button(occurrence, now, is_today))

        layout.addStretch()
        return frame

    def _build_event_button(
        self,
        occurrence: EventOccurrence,
        now: datetime,
        is_today: bool,
    ) -> ClickableEventLabel:
        is_past = occurrence.start_at < now

        btn = ClickableEventLabel(
            occurrence=occurrence,
            text=f"{self._format_time(occurrence.start_at)}  {occurrence.name}",
            on_click=self._open_details,
        )
        btn.setFont(self._event_font(is_past))
        btn.setStyleSheet(self._event_button_style(is_past, is_today))
        return btn

    def _event_font(self, is_past: bool) -> QFont:
        font = QFont("Arial", 8)
        font.setStrikeOut(is_past)
        return font

    def _event_button_style(self, is_past: bool, is_today: bool) -> str:
        if is_past:
            return s.CALENDAR_EVENT_BUTTON_PAST_STYLE
        if is_today:
            return s.CALENDAR_EVENT_BUTTON_TODAY_STYLE
        return s.CALENDAR_EVENT_BUTTON_NORMAL_STYLE

    # ============================================================
    # DETAIL POPUP
    # ============================================================

    def _open_details(self, occurrence: EventOccurrence):
        if self.detail_popup is None:
            return

        self.detail_popup.show_event(occurrence, self.time_format)
        self._center_detail_popup()

        # SingleShot(0) pomaga, če popup po show_event šele nato dobi final sizeHint.
        QTimer.singleShot(0, self._center_detail_popup)

    def _center_detail_popup(self):
        if self.detail_popup is None or not self.detail_popup.isVisible():
            return

        popup_w = self.detail_popup.frameGeometry().width()
        popup_h = self.detail_popup.frameGeometry().height()

        global_top_left = self.mapToGlobal(self.rect().topLeft())
        x = global_top_left.x() + (self.width() - popup_w) // 2
        y = global_top_left.y() + (self.height() - popup_h) // 2

        self.detail_popup.move(x, y)

    def closeEvent(self, event):
        if self.detail_popup is not None:
            self.detail_popup.hide()
        super().closeEvent(event)

    # ============================================================
    # LAYOUT / SCROLL HELPERS
    # ============================================================

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _scrollbar_width(self) -> int:
        return self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)

    def _update_scrollbar_spacer(self):
        width = self.week_scroll.verticalScrollBar().width()
        if width <= 0:
            width = self.week_scroll.verticalScrollBar().sizeHint().width()

        self.header_scroll_spacer.setFixedWidth(width)
        self.underline_scroll_spacer.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrollbar_spacer()

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
    # FORMAT
    # ============================================================

    def _format_time(self, dt: datetime) -> str:
        """
        Uporabi userjev settings format:
        - 24h
        - 12h AM/PM
        """
        if self.time_format == "12h":
            return dt.strftime("%I:%M %p").lstrip("0")
        return dt.strftime("%H:%M")