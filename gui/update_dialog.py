from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui import styles as s
from gui.tabs.shared import SETTINGS_STYLE, style_footer_button, style_save_button
from runtime.update_checker import UpdateInfo


class UpdateDialog(QDialog):
    def __init__(self, update_info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.update_info = update_info

        self.setWindowTitle("New version available")
        self.setModal(True)
        self.setFixedSize(560, 460)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(SETTINGS_STYLE)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_body())
        root.addWidget(self._build_footer())

    def _build_title_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(46)
        bar.setStyleSheet(s.WINDOW_TITLEBAR_STYLE)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 8, 0)

        title = QLabel("New version available")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet(s.WINDOW_TITLE_TEXT_STYLE)
        layout.addWidget(title)

        layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(s.WINDOW_CLOSE_BUTTON_STYLE)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        intro = QLabel(
            f"A new version of Legends Overlay is available.\n"
            f"Current: {self.update_info.current_version}   →   Latest: {self.update_info.latest_version}"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        notes_title = QLabel("Patch notes")
        notes_title.setStyleSheet(s.SECTION_TITLE_STYLE)
        layout.addWidget(notes_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        notes_wrap = QWidget()
        notes_layout = QVBoxLayout(notes_wrap)
        notes_layout.setContentsMargins(0, 0, 0, 0)

        notes = QLabel(self.update_info.patch_notes)
        notes.setWordWrap(True)
        notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        notes_layout.addWidget(notes)
        notes_layout.addStretch()

        scroll.setWidget(notes_wrap)
        layout.addWidget(scroll)

        return body

    def _build_footer(self) -> QFrame:
        footer = QFrame()
        footer.setFixedHeight(54)
        footer.setStyleSheet(s.WINDOW_FOOTER_STYLE)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)

        layout.addStretch()

        self.later_btn = QPushButton("Later")
        style_footer_button(self.later_btn)
        self.later_btn.clicked.connect(self.reject)

        self.update_btn = QPushButton("Update")
        style_save_button(self.update_btn)
        self.update_btn.clicked.connect(self.accept)

        layout.addWidget(self.later_btn)
        layout.addSpacing(8)
        layout.addWidget(self.update_btn)

        return footer
    
    def set_updating_state(self, updating: bool):
        self.later_btn.setEnabled(not updating)
        self.update_btn.setEnabled(not updating)
        self.update_btn.setText("Updating..." if updating else "Update")