from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from runtime.event_engine import EventOccurrence


SERVER_TZ = timezone(timedelta(hours=3))


class EventDetailPopup(QWidget):
    """
    Lightweight detail popup za en event occurrence.

    Popup je purely UI:
    - dobi EventOccurrence
    - pretvori podatke v rich-text
    - izračuna svojo velikost
    - prikaže vsebino

    Ne vsebuje business logike za evente.
    """

    WIDTH = 680
    MIN_HEIGHT = 220
    WINDOW_EXTRA_HEIGHT = 16

    def __init__(self, parent=None):
        # Popup je top-level widget, ne child znotraj calendar layouta.
        # Parent hranimo samo kot anchor/context, ne kot Qt parent za layout hierarhijo.
        super().__init__(None)

        self._anchor_parent = parent

        self.setObjectName("EventDetailPopupWindow")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

        self._build_ui()
        self.hide()

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("eventPopupCard")
        self.card.setFixedWidth(self.WIDTH)
        self.card.setStyleSheet(s.CALENDAR_POPUP_STYLE)
        outer.addWidget(self.card)

        self.root = QVBoxLayout(self.card)
        self.root.setContentsMargins(12, 12, 12, 12)
        self.root.setSpacing(0)
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.root.addLayout(self._build_title_row())
        self.root.addSpacing(12)
        self.root.addWidget(self._build_info_frame())
        self.root.addSpacing(10)
        self.root.addWidget(self._build_body_frame())

    def _build_title_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_lbl = QLabel("Event")
        self.title_lbl.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(s.CALENDAR_POPUP_TITLE_STYLE)
        self.title_lbl.setWordWrap(True)
        self.title_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.title_lbl)

        layout.addStretch()

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet(s.CALENDAR_POPUP_CLOSE_BUTTON_STYLE)
        self.close_btn.clicked.connect(self.hide)
        layout.addWidget(self.close_btn)

        return layout

    def _build_info_frame(self) -> QFrame:
        self.info_frame = QFrame()
        self.info_frame.setStyleSheet(s.CALENDAR_POPUP_INFO_FRAME_STYLE)
        self.info_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        layout = QVBoxLayout(self.info_frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.local_time_lbl = self._make_rich_label(s.CALENDAR_POPUP_INFO_TEXT_STYLE)
        self.server_time_lbl = self._make_rich_label(s.CALENDAR_POPUP_INFO_SUBTLE_STYLE)
        self.type_lbl = self._make_rich_label(s.CALENDAR_POPUP_INFO_TEXT_STYLE)
        self.duration_lbl = self._make_rich_label(s.CALENDAR_POPUP_INFO_TEXT_STYLE)
        self.registration_lbl = self._make_rich_label(s.CALENDAR_POPUP_INFO_WARNING_STYLE)
        self.registration_lbl.hide()

        for label in (
            self.local_time_lbl,
            self.server_time_lbl,
            self.type_lbl,
            self.duration_lbl,
            self.registration_lbl,
        ):
            layout.addWidget(label, 0)

        return self.info_frame

    def _build_body_frame(self) -> QFrame:
        self.body_frame = QFrame()
        self.body_frame.setStyleSheet(s.CALENDAR_POPUP_BODY_FRAME_STYLE)
        self.body_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )

        layout = QVBoxLayout(self.body_frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.body_label = QLabel("")
        self.body_label.setTextFormat(Qt.TextFormat.RichText)
        self.body_label.setWordWrap(True)
        self.body_label.setOpenExternalLinks(False)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.body_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.body_label.setMinimumWidth(0)
        self.body_label.setStyleSheet("background: transparent; border: none;")

        layout.addWidget(self.body_label, 0)
        return self.body_frame

    def _make_rich_label(self, style: str) -> QLabel:
        label = QLabel("")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        label.setStyleSheet(style)
        return label

    # ============================================================
    # PUBLIC RENDER API
    # ============================================================

    def show_event(self, occurrence: EventOccurrence, time_format: str):
        """
        Napolni popup z event podatki in ga prikaže.

        Pomembno:
        najprej ga skrijemo, da se izognemo vizualnemu 'skoku'
        med ponovnim sizingom in posodabljanjem vsebine.
        """
        self.hide()

        details = occurrence.details or {}
        registration_before = self._get_registration_before(details)

        self.title_lbl.setText(occurrence.name)
        self.local_time_lbl.setText(
            f"<b>Local time:</b> {self._format_time(occurrence.start_at, time_format)}"
        )
        self.server_time_lbl.setText(
            f"<b>Server time:</b> {self._server_time_string(occurrence.start_at)} (GMT+3)"
        )
        self.type_lbl.setText(f"<b>Type:</b> {occurrence.event_type}")
        self.duration_lbl.setText(f"<b>Duration:</b> {occurrence.duration_minutes} min")

        if registration_before:
            self.registration_lbl.setText(
                f"<b>Registration:</b> {registration_before} min before"
            )
            self.registration_lbl.show()
        else:
            self.registration_lbl.hide()

        self.body_label.setText(self._build_body_html(details))

        self._finalize_size()
        self.show()
        self.raise_()

    # ============================================================
    # DATA -> HTML
    # ============================================================

    def _build_body_html(self, details: dict) -> str:
        parts: list[str] = []

        desc = details.get("desc")
        if desc:
            parts.append(self._build_description_block(desc))

        rewards = details.get("rewards", [])
        if rewards:
            parts.append(self._build_list_block("Rewards:", rewards, "#00FF00"))

        requirements = details.get("requirements", [])
        if requirements:
            parts.append(self._build_list_block("Requirements:", requirements, "#FF4500"))

        quests = details.get("quests", [])
        if quests and not isinstance(quests, list):
            quests = [quests]
        if quests:
            parts.append(self._build_list_block("Related Quests:", quests, "#00CCFF"))

        return "".join(parts)

    def _build_description_block(self, text: str) -> str:
        return (
            '<div style="margin-bottom:10px;">'
            '<div style="color:#d4c5a1; font-weight:bold; margin-bottom:4px;">Description:</div>'
            f'<div style="color:#d4c5a1; margin-left:12px;">{self._escape(text)}</div>'
            "</div>"
        )

    def _build_list_block(self, title: str, items: list[str], color: str) -> str:
        html = [
            '<div style="margin-bottom:10px;">',
            f'<div style="color:#d4c5a1; font-weight:bold; margin-bottom:4px;">{self._escape(title)}</div>',
        ]

        for item in items:
            html.append(
                f'<div style="color:{color}; margin-left:12px;">• {self._escape(str(item))}</div>'
            )

        html.append("</div>")
        return "".join(html)

    @staticmethod
    def _get_registration_before(details: dict) -> int:
        if not isinstance(details, dict):
            return 0
        return int(details.get("registration_time_before", 0) or 0)

    # ============================================================
    # SIZE / LAYOUT
    # ============================================================

    def _finalize_size(self):
        """
        Po posodobitvi texta prisilimo relayout in nato popup resize-amo.

        Zakaj to rabimo:
        rich-text QLabel sizeHint se lahko spremeni glede na content,
        zato popup po show_event() ne sme uporabljati stare velikosti.
        """
        self.info_frame.updateGeometry()
        self.body_frame.updateGeometry()
        self.body_label.updateGeometry()

        self.root.invalidate()
        self.root.activate()

        self.info_frame.adjustSize()
        self.body_label.adjustSize()
        self.body_frame.adjustSize()
        self.card.adjustSize()
        self.adjustSize()

        content_height = max(self.card.sizeHint().height(), self.MIN_HEIGHT)
        self.resize(self.WIDTH, content_height + self.WINDOW_EXTRA_HEIGHT)

    # ============================================================
    # FORMAT HELPERS
    # ============================================================

    @staticmethod
    def _escape(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    @staticmethod
    def _format_time(dt: datetime, fmt: str) -> str:
        if fmt == "12h":
            return dt.strftime("%I:%M %p").lstrip("0")
        return dt.strftime("%H:%M")

    @staticmethod
    def _server_time_string(local_dt: datetime) -> str:
        return local_dt.astimezone().astimezone(SERVER_TZ).strftime("%H:%M")