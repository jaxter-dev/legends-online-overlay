from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from gui import styles as s
from gui.tabs.shared import style_small_button
from gui.unique_setup_window import UniqueSetupWindow


class UniquesTab(QWidget):
    def __init__(self, settings_data: dict | None = None, parent=None):
        super().__init__(parent)

        self.settings_data = settings_data or {}
        self._setup_window = None

        self.setStyleSheet(s.ROOT_STYLE)
        self._build_ui()

    def _create_section(self, title: str):
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

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(8)

        root.addWidget(self._build_ocr_section())
        root.addWidget(self._build_unique_settings_section())
        root.addStretch()

    def _build_ocr_section(self) -> QWidget:
        section, layout = self._create_section("OCR")

        ocr_info = QLabel("Under development! OCR will be released in upcoming versions.")
        ocr_info.setStyleSheet(s.INFO_STYLE)
        ocr_info.setWordWrap(True)

        layout.addWidget(ocr_info)
        return section

    def _build_unique_settings_section(self) -> QWidget:
        section, layout = self._create_section("Unique Settings")

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title = QLabel("Select which uniques are enabled")
        title.setStyleSheet("color: #c8c8c8; font-size: 10px; background: transparent; border: none;")

        sub = QLabel("Enabled uniques appear on overlay and can trigger alerts.")
        sub.setStyleSheet(s.INFO_STYLE)
        sub.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(sub)

        self.btn_setup = QPushButton("Setup")
        self.btn_setup.setFixedWidth(100)
        style_small_button(self.btn_setup)
        self.btn_setup.clicked.connect(self._open_setup)

        row.addLayout(text_col, 1)
        row.addWidget(self.btn_setup)

        layout.addLayout(row)
        return section

    def _open_setup(self):
        if self._setup_window is None:
            self._setup_window = UniqueSetupWindow(
                settings_data=self.settings_data,
                parent=self.window(),
            )
            self._setup_window.saved.connect(self._apply_unique_selection)
            self._setup_window.destroyed.connect(self._on_setup_closed)

        self._setup_window.show()
        self._setup_window.raise_()

    def _apply_unique_selection(self, enabled_uniques: dict):
        uniques_cfg = dict(self.settings_data.get("uniques", {}))
        uniques_cfg["enabled_uniques"] = dict(enabled_uniques)
        self.settings_data["uniques"] = uniques_cfg

    def _on_setup_closed(self):
        self._setup_window = None

    def collect_settings(self) -> dict:
        uniques_cfg = dict(self.settings_data.get("uniques", {}))
        return {
            "uniques": uniques_cfg
        }