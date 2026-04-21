import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
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
from gui.tabs.shared import style_footer_button, style_save_button
from runtime.app_paths import get_uniques_path

class UniqueToggle(QPushButton):
    """
    Preprost on/off toggle za enable state unique-a.
    """

    def __init__(self, checked: bool, parent=None):
        super().__init__("Enabled", parent)

        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(84, 24)

        self.toggled.connect(self._update_style)
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(
            s.TOGGLE_ON_STYLE if self.isChecked() else s.TOGGLE_OFF_STYLE
        )


class UniqueSetupWindow(QWidget):
    """
    Window za izbiro, kateri unique-i so enabled.

    Pomemben output:
        enabled_uniques = {
            "unique_id": True / False
        }
    """

    saved = pyqtSignal(dict)

    def __init__(self, settings_data: dict | None = None, parent=None):
        super().__init__(parent)

        self.settings_data = settings_data or {}
        self.uniques_path = get_uniques_path()

        self._drag_pos = None
        self._toggle_map: dict[str, UniqueToggle] = {}
        self._uniques = self._load_uniques()

        self.setStyleSheet(s.ROOT_STYLE)

        self._setup_window()
        self._build_ui()
        self._load_settings()
        self._center_on_parent()

    # ============================================================
    # WINDOW SETUP
    # ============================================================

    def _setup_window(self):
        self.setWindowTitle("Unique Setup")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setFixedSize(460, 560)

    # ============================================================
    # LOAD / NORMALIZE
    # ============================================================

    def _load_uniques(self) -> list[dict]:
        """
        Load unique definitions from uniques.json.

        Poskrbimo, da ima vsak unique stabilen 'id',
        tudi če source JSON tega še nima.
        """
        try:
            with self.uniques_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        items: list[dict] = []

        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue

            normalized = dict(item)
            normalized["id"] = self._get_unique_id(item, index)
            items.append(normalized)

        return items

    def _get_unique_id(self, unique: dict, index: int) -> str:
        """
        Vrni explicit id, če obstaja.
        Sicer ga zgradi iz imena.

        To ohrani kompatibilnost s starejšimi uniques.json verzijami.
        """
        explicit_id = str(unique.get("id", "")).strip()
        if explicit_id:
            return explicit_id

        name = str(unique.get("name", f"unique_{index}")).strip().lower()
        return (
            name.replace("[", "")
            .replace("]", "")
            .replace("(", "")
            .replace(")", "")
            .replace("-", "_")
            .replace(" ", "_")
        )

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_content_host())
        root.addWidget(self._build_footer())

    def _build_title_bar(self) -> QFrame:
        title_bar = QFrame()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet(s.WINDOW_TITLEBAR_STYLE)

        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(12, 0, 8, 0)

        title = QLabel("Unique Setup")
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

    def _build_content_host(self) -> QWidget:
        host = QWidget()

        content = QVBoxLayout(host)
        content.setContentsMargins(12, 10, 12, 10)
        content.setSpacing(8)

        info = QLabel("Enabled uniques appear on overlay and can trigger alerts.")
        info.setStyleSheet(s.INFO_STYLE)
        content.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(s.SCROLLBAR_STYLE)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(6)

        for unique in self._uniques:
            scroll_layout.addWidget(self._build_unique_card(unique))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)

        content.addWidget(scroll)
        return host

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(52)
        footer.setStyleSheet(s.FOOTER_DARK_STYLE)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        style_footer_button(btn_cancel)
        btn_cancel.clicked.connect(self.close)

        btn_save = QPushButton("Save")
        style_save_button(btn_save)
        btn_save.clicked.connect(self._save_and_close)

        layout.addWidget(btn_cancel)
        layout.addSpacing(8)
        layout.addWidget(btn_save)

        return footer

    def _build_unique_card(self, unique: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("itemCard")
        card.setStyleSheet(s.CARD_STYLE)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        layout.addWidget(self._build_text_column(unique), 1)

        toggle = UniqueToggle(True)
        self._toggle_map[str(unique["id"])] = toggle
        layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)

        return card

    def _build_text_column(self, unique: dict) -> QWidget:
        text_wrap = QWidget()
        text_wrap.setStyleSheet("background: transparent; border: none;")

        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        name_lbl = QLabel(str(unique.get("name", "Unknown")))
        name_lbl.setStyleSheet(s.TITLE_STYLE)
        text_col.addWidget(name_lbl)

        short_name = str(unique.get("short_name", "")).strip()
        if short_name:
            short_lbl = QLabel(short_name)
            short_lbl.setStyleSheet(s.SUBTITLE_STYLE)
            text_col.addWidget(short_lbl)

        return text_wrap

    # ============================================================
    # SETTINGS SYNC
    # ============================================================

    def _load_settings(self):
        uniques_cfg = self.settings_data.get("uniques", {})
        enabled_uniques = uniques_cfg.get("enabled_uniques", {})

        for unique_id, toggle in self._toggle_map.items():
            toggle.setChecked(bool(enabled_uniques.get(unique_id, True)))

    def _save_and_close(self):
        enabled_uniques = {
            unique_id: toggle.isChecked()
            for unique_id, toggle in self._toggle_map.items()
        }
        self.saved.emit(enabled_uniques)
        self.close()

    # ============================================================
    # POSITION / DRAG
    # ============================================================

    def _center_on_parent(self):
        parent = self.parent()
        if parent is not None:
            parent_geo = parent.frameGeometry()
            x = parent_geo.x() + (parent_geo.width() - self.width()) // 2
            y = parent_geo.y() + (parent_geo.height() - self.height()) // 2
            self.move(x, y)
            return

        screen = self.screen()
        if screen is None:
            return

        geometry = screen.geometry()
        x = (geometry.width() - self.width()) // 2
        y = (geometry.height() - self.height()) // 2
        self.move(x, y)

    def _start_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _do_drag(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)