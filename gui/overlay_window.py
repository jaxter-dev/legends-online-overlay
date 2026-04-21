import os
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.state import OverlayState
from gui import styles as s
from runtime.resource_path import resource_path

@dataclass(slots=True)
class RowWidgets:
    """
    Majhen helper, da ne lepimo custom atributov na QWidget.

    Prej je row widget dobil:
    - row.left_label
    - row.right_label

    To sicer dela, ampak je manj pregledno.
    Tako je bolj jasno, kaj ena vrstica vsebuje.
    """
    container: QWidget
    left_label: QLabel
    right_label: QLabel


class OverlayWindow(QWidget):
    """
    Visual overlay window (UI only).

    Odgovornosti:
    - zgradi overlay UI
    - prikaže vrstice, ki jih dobi od controllerja
    - omogoča drag premikanje, če overlay ni zaklenjen

    Pomembno:
    - ne vsebuje business logike za evente ali unique timerje
    - ne sme jemati fokusa igri
    """

    position_changed = pyqtSignal(int, int)
    uniques_clicked = pyqtSignal()
    daily_check_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.dragging = False
        self.drag_offset = None
        self._drag_start_pos = None
        self.is_locked = False

        # Reuse row widgetov je bolj lightweight kot ponovno ustvarjanje.
        self.row_widgets: list[RowWidgets] = []

        self._setup_window()
        self._build_ui()

    # ============================================================
    # WINDOW SETUP
    # ============================================================

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(220)
        self.move(100, 100)

    def set_locked(self, locked: bool):
        """
        Če je overlay zaklenjen, ga ni mogoče premikati z dragom.
        """
        self.is_locked = bool(locked)

    # ============================================================
    # UI BUILD
    # ============================================================

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.main_frame = QFrame()
        self.main_frame.setObjectName("overlayPanel")
        self.main_frame.setStyleSheet(s.PANEL_STYLE)
        root_layout.addWidget(self.main_frame, 0, Qt.AlignmentFlag.AlignTop)

        self.main_layout = QVBoxLayout(self.main_frame)
        self.main_layout.setContentsMargins(10, 5, 10, 10)
        self.main_layout.setSpacing(4)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._build_header()
        self._build_rows_area()
        self._build_daily_banner()
        self._install_drag_handlers()

    def _build_header(self):
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        self.title_label = QLabel()
        self.title_label.setStyleSheet(s.TITLE_STYLE)
        self.title_label.setFixedHeight(20)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        logo_path = resource_path("assets", "legends_logo.png")
        logo_px = QPixmap(str(logo_path))

        if not logo_px.isNull():
            self.title_label.setPixmap(
                logo_px.scaledToHeight(
                    20,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.title_label.setText("Legends Overlay")
            self.title_label.setFont(QFont("Tahoma", 10, QFont.Weight.Bold))

        header.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        self.btn_calendar = self._create_mini_button(str(resource_path("assets", "icon_calendar.png")))
        self.btn_uniques = self._create_mini_button(str(resource_path("assets", "icon_unique.png")))
        self.btn_settings = self._create_mini_button(str(resource_path("assets", "icon_settings.png")))

        self.btn_uniques.clicked.connect(self.uniques_clicked.emit)

        header.addWidget(self.btn_calendar, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.btn_uniques, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.btn_settings, 0, Qt.AlignmentFlag.AlignVCenter)

        self.main_layout.addLayout(header)

    def _build_rows_area(self):
        self.rows_container = QVBoxLayout()
        self.rows_container.setContentsMargins(0, 0, 0, 0)
        self.rows_container.setSpacing(1)
        self.rows_container.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.rows_host = QWidget()
        self.rows_host.setStyleSheet("background: transparent;")
        self.rows_host.setLayout(self.rows_container)

        self.main_layout.addWidget(self.rows_host, 0, Qt.AlignmentFlag.AlignTop)

    def _create_mini_button(self, icon_path: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(s.HEADER_BUTTON_STYLE)

        if os.path.exists(icon_path):
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(18, 18))

        return btn

    # ============================================================
    # ROW BUILD / RENDER
    # ============================================================

    def _create_row(self) -> RowWidgets:
        """
        Ustvari eno reusable overlay vrstico.

        Vsaka vrstica ima:
        - levi label: ime eventa / unique-a
        - desni label: countdown / status text
        """
        row = QWidget()
        row.setStyleSheet(s.ROW_BASE_STYLE)
        row.setFixedHeight(18)
        row.setMinimumHeight(18)
        row.setMaximumHeight(18)

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        left = QLabel("")
        right = QLabel("")

        font = QFont("Tahoma", 8, QFont.Weight.Bold)
        left.setFont(font)
        right.setFont(font)

        left.setWordWrap(False)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setFixedWidth(70)

        row_layout.addWidget(left, 1)
        row_layout.addWidget(right)

        return RowWidgets(
            container=row,
            left_label=left,
            right_label=right,
        )

    def _ensure_row_count(self, count: int):
        """
        Overlay vrstice ustvarimo samo po potrebi.
        To pomeni manj widget churn-a med refreshi.
        """
        while len(self.row_widgets) < count:
            row = self._create_row()
            self.rows_container.addWidget(row.container)
            self.row_widgets.append(row)

            row.container.installEventFilter(self)
            for child in row.container.findChildren(QWidget):
                child.installEventFilter(self)

    def _apply_row(self, row: RowWidgets, left_text: str, right_text: str, color: str):
        row.left_label.setText(left_text)
        row.right_label.setText(right_text)

        text_style = s.ROW_TEXT_STYLE.format(color=color)
        row.left_label.setStyleSheet(text_style)
        row.right_label.setStyleSheet(text_style)

    def render_state(self, state: OverlayState):
        """
        Controller pošlje OverlayState, UI ga samo nariše.

        Pomembno:
        - tukaj ne odločamo, KAJ se prikaže
        - tukaj odločamo samo, KAKO se to izriše
        """
        if not self.title_label.pixmap():
            self.title_label.setText(state.title)

        self._ensure_row_count(len(state.rows))
        visible_count = len(state.rows)

        for index, row_state in enumerate(state.rows):
            row = self.row_widgets[index]
            self._apply_row(
                row=row,
                left_text=row_state.label,
                right_text=row_state.value,
                color=row_state.color,
            )
            row.container.show()

        for index in range(visible_count, len(self.row_widgets)):
            self.row_widgets[index].container.hide()

        self._refresh_layout_height()

    # ============================================================
    # DRAG / POSITION
    # ============================================================

    def _install_drag_handlers(self):
        """
        Drag logika je narejena prek eventFilter, da lahko premikaš overlay
        tudi če klikneš na child widgete, ne samo na golo ozadje.
        """
        self.installEventFilter(self)
        self.main_frame.installEventFilter(self)

        for child in self.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):
        """
        Prestrezanje mouse eventov za drag.

        Gumbi v headerju so izključeni, da normalno klikajo.
        """
        if obj in (self.btn_calendar, self.btn_uniques, self.btn_settings):
            return super().eventFilter(obj, event)

        if self.is_locked:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.MouseButtonPress:
            return self._handle_mouse_press(event)

        if event.type() == QEvent.Type.MouseMove:
            return self._handle_mouse_move(event)

        if event.type() == QEvent.Type.MouseButtonRelease:
            return self._handle_mouse_release(event)

        return super().eventFilter(obj, event)

    def _handle_mouse_press(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        self.dragging = True
        self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._drag_start_pos = self.pos()
        return True

    def _handle_mouse_move(self, event) -> bool:
        if not self.dragging or self.drag_offset is None:
            return False

        new_pos = event.globalPosition().toPoint() - self.drag_offset
        self.move(new_pos)
        return True

    def _handle_mouse_release(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        self.dragging = False
        self.drag_offset = None

        # position_changed pošljemo samo, če se je overlay dejansko premaknil.
        if self._drag_start_pos is None or self.pos() != self._drag_start_pos:
            self.position_changed.emit(int(self.x()), int(self.y()))

        self._drag_start_pos = None
        return True

    # ============================================================
    # LAYOUT / SIZE
    # ============================================================

    def _refresh_layout_height(self):
        """
        Overlay naj raste / pada glede na število vidnih vrstic.

        Namenoma ne uporabljamo težjih view/model komponent,
        ker je overlay majhen in se osvežuje pogosto.
        """
        try:
            self.rows_host.updateGeometry()
            self.main_frame.updateGeometry()
            self.main_layout.invalidate()
            self.main_layout.activate()

            self.main_frame.adjustSize()

            desired_height = max(52, self.main_frame.sizeHint().height())
            if abs(self.height() - desired_height) <= 1:
                return

            self.setFixedHeight(desired_height)
        except Exception:
            # Overlay ne sme pasti zaradi layout edge case-a.
            pass

    def _build_daily_banner(self):
        self.daily_banner = QPushButton("Daily check in reminder")
        self.daily_banner.setVisible(False)
        self.daily_banner.setFixedHeight(24)
        self.daily_banner.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.daily_banner.setStyleSheet("""
    QPushButton {
        background: rgba(76, 175, 80, 0.92);
        color: white;
        border: none;
        border-radius: 6px;
        font-size: 10px;
        font-weight: bold;
        text-align: center;
        padding: 2px 8px;
    }
    QPushButton:hover {
        background: rgba(88, 190, 92, 0.98);
    }
    """)
        self.daily_banner.clicked.connect(self.daily_check_clicked.emit)

        self.main_layout.addSpacing(4)
        self.main_layout.addWidget(self.daily_banner, 0, Qt.AlignmentFlag.AlignTop)

    def set_daily_banner_visible(self, visible: bool):
        self.daily_banner.setVisible(bool(visible))
        self._refresh_layout_height()