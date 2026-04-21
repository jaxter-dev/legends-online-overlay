from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.tabs.shared import BTN_HEIGHT, style_small_button


class TimeToggle(QPushButton):
    """
    Toggle za posamezen event time-slot.

    Primer ključa v settings:
        battle_1800 -> True / False
    """

    def __init__(self, time_str: str, checked: bool, parent=None):
        super().__init__(time_str, parent)

        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedHeight(22)

        # Gumb naj bo ravno dovolj širok za text + malo paddinga.
        try:
            width = max(50, self.fontMetrics().horizontalAdvance(time_str) + 22)
            self.setMinimumWidth(width)
        except Exception:
            pass

        self.toggled.connect(self._update_style)
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(
            s.TOGGLE_ON_STYLE if self.isChecked() else s.TOGGLE_OFF_STYLE
        )


class NotificationsTab(QWidget):
    """
    Scheduled event configuration tab.

    One source of truth:
    - enabled = shown on overlay
    - enabled = eligible for alerts

    Ta tab ne odloča, kako overlay deluje.
    Samo ureja config za event/time-slot enable state.
    """

    def __init__(self, settings_data: dict | None = None, events_data: list | None = None):
        super().__init__()

        self.settings_data = settings_data or {}
        self.events_data = events_data or []

        # key -> TimeToggle
        self._enabled_toggles: dict[str, TimeToggle] = {}

        self.setStyleSheet(s.ROOT_STYLE)
        self._build_ui()

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.setSpacing(8)

        outer.addWidget(self._build_header_section())
        outer.addWidget(self._build_scroll_area())

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

    def _build_header_section(self) -> QWidget:
        section, layout = self._create_section("Scheduled Events")

        info = QLabel(
            "Enabled time-slots are shown on the overlay and can trigger alerts."
        )
        info.setStyleSheet(s.INFO_STYLE)
        info.setWordWrap(True)
        layout.addWidget(info)

        quick_row = QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(6)

        self.btn_enable_all = QPushButton("Enable All")
        self.btn_disable_all = QPushButton("Disable All")

        for btn in (self.btn_enable_all, self.btn_disable_all):
            btn.setFixedSize(100, BTN_HEIGHT)
            style_small_button(btn)

        self.btn_enable_all.clicked.connect(self._enable_all)
        self.btn_disable_all.clicked.connect(self._disable_all)

        quick_row.addStretch()
        quick_row.addWidget(self.btn_enable_all)
        quick_row.addWidget(self.btn_disable_all)

        layout.addLayout(quick_row)
        return section

    def _build_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(s.SCROLLBAR_STYLE)

        content = QWidget()
        content.setStyleSheet("background: transparent;")

        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 2, 4, 4)
        self.content_layout.setSpacing(6)

        self._populate_event_cards()

        self.content_layout.addStretch()
        scroll.setWidget(content)

        self.scroll = scroll
        return scroll

    # ============================================================
    # EVENT CARD BUILDING
    # ============================================================

    def _populate_event_cards(self):
        notif_cfg = self.settings_data.get("notifications", {})
        enabled_map = notif_cfg.get("enabled_events", {})

        for event in self.events_data:
            card = self._build_event_card_from_event(event, enabled_map)
            if card is not None:
                self.content_layout.addWidget(card)

    def _build_event_card_from_event(self, event: dict, enabled_map: dict) -> QFrame | None:
        event_id = self._get_event_id(event)
        event_name = str(event.get("name", "Unknown"))
        event_type = str(event.get("type", "Event"))
        times = self._normalize_times(event.get("time", []))

        if not times:
            return None

        return self._build_event_card(
            event_id=event_id,
            event_name=event_name,
            event_type=event_type,
            times=times,
            enabled_map=enabled_map,
        )

    def _get_event_id(self, event: dict) -> str:
        """
        Uporabi explicit id, če obstaja.
        Sicer naredi fallback iz imena, da ostane kompatibilno s starimi eventi.
        """
        raw_id = str(event.get("id", "")).strip()
        if raw_id:
            return raw_id

        return str(event.get("name", "unknown")).lower().replace(" ", "_")

    def _normalize_times(self, times_value) -> list[str]:
        """
        Event time je lahko:
        - string
        - list[str]

        Vedno ga normaliziramo v list[str].
        """
        if isinstance(times_value, str):
            return [times_value]

        if isinstance(times_value, list):
            return [str(t) for t in times_value if str(t).strip()]

        return []

    def _build_event_card(
        self,
        event_id: str,
        event_name: str,
        event_type: str,
        times: list[str],
        enabled_map: dict,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("itemCard")
        card.setStyleSheet(s.CARD_STYLE)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(6)

        card_layout.addWidget(self._build_event_title_block(event_name, event_type))
        card_layout.addLayout(self._build_enabled_row(event_id, times, enabled_map))

        return card

    def _build_event_title_block(self, event_name: str, event_type: str) -> QWidget:
        title_wrap = QWidget()
        title_wrap.setStyleSheet("background: transparent; border: none;")

        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)

        title = QLabel(event_name)
        title.setStyleSheet(s.TITLE_STYLE)

        subtitle = QLabel(event_type)
        subtitle.setStyleSheet(s.SUBTITLE_STYLE)

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        return title_wrap

    def _build_enabled_row(self, event_id: str, times: list[str], enabled_map: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        enabled_label = QLabel("Enabled:")
        enabled_label.setStyleSheet(s.ROW_LABEL_STYLE)
        row.addWidget(enabled_label)

        for time_str in times:
            key = self._make_enabled_key(event_id, time_str)
            enabled = bool(enabled_map.get(key, True))

            toggle = TimeToggle(time_str, enabled)
            self._enabled_toggles[key] = toggle
            row.addWidget(toggle)

        row.addStretch()
        return row

    def _make_enabled_key(self, event_id: str, time_str: str) -> str:
        """
        Ključ mora ostati stabilen, ker ga uporablja:
        - settings.json
        - overlay filtering
        - alert filtering
        """
        return f"{event_id}_{time_str.replace(':', '')}"

    # ============================================================
    # ACTIONS
    # ============================================================

    def _enable_all(self):
        for toggle in self._enabled_toggles.values():
            toggle.setChecked(True)

    def _disable_all(self):
        for toggle in self._enabled_toggles.values():
            toggle.setChecked(False)

    # ============================================================
    # SAVE / EXPORT
    # ============================================================

    def collect_settings(self) -> dict:
        """
        Vrne samo notifications del settings,
        da ga parent settings window lahko merge-a nazaj.
        """
        notif_cfg = dict(self.settings_data.get("notifications", {}))
        notif_cfg["enabled_events"] = {
            key: toggle.isChecked()
            for key, toggle in self._enabled_toggles.items()
        }

        return {
            "notifications": notif_cfg,
        }