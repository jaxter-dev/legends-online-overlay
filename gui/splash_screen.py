from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

from gui import styles as s
from runtime.resource_path import resource_path

class SplashScreen(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(460, 320)
        self.setObjectName("startupSplash")

        self.setStyleSheet(
            """
            QWidget#startupSplash {
                background-color: rgb(34, 37, 43);
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 14px;
            }
            QLabel {
                color: rgb(235, 235, 235);
                background: transparent;
            }
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                background: rgb(46, 49, 56);
                text-align: center;
                color: rgb(220, 220, 220);
                min-height: 12px;
                max-height: 12px;
            }
            QProgressBar::chunk {
                background: rgb(110, 130, 180);
                border-radius: 5px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setMinimumHeight(140)

        logo_path = resource_path("assets", "legends_logo.png")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                self.logo_label.setPixmap(
                    pixmap.scaled(
                        180,
                        180,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.logo_label.setText("LEGENDS")
        else:
            self.logo_label.setText("LEGENDS")

        self.logo_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))

        self.title_label = QLabel("Legends Overlay")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))

        self.status_label = QLabel("Starting...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setFont(QFont("Arial", 10))

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)

        layout.addStretch()
        layout.addWidget(self.logo_label)
        layout.addWidget(self.title_label)
        layout.addSpacing(4)
        layout.addWidget(self.status_label)
        layout.addSpacing(6)
        layout.addWidget(self.progress)
        layout.addStretch()

        self.center_on_screen()

    def center_on_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return

        geometry = screen.availableGeometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + (geometry.height() - self.height()) // 2
        self.move(x, y)

    def set_status(self, text: str):
        self.status_label.setText(str(text))
        QApplication.processEvents()