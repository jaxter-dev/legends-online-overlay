from collections import deque

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget
from PyQt6.QtWidgets import QGraphicsOpacityEffect

from gui import styles as s


class ToastPopup(QFrame):
    def __init__(self, title: str, message: str, parent: QWidget | None = None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.setObjectName("toastPopup")
        self.setStyleSheet(s.TOAST_STYLE)
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.title_label = QLabel(str(title))
        self.title_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.title_label.setWordWrap(True)

        self.message_label = QLabel(str(message))
        self.message_label.setFont(QFont("Arial", 9))
        self.message_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)

        self.adjustSize()

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self.opacity_effect)

        self.fade_in_anim = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade_in_anim.setDuration(220)
        self.fade_in_anim.setStartValue(0.0)
        self.fade_in_anim.setEndValue(1.0)
        self.fade_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.fade_out_anim = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.fade_out_anim.setDuration(220)
        self.fade_out_anim.setStartValue(1.0)
        self.fade_out_anim.setEndValue(0.0)
        self.fade_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self.slide_in_anim = QPropertyAnimation(self, b"pos", self)
        self.slide_in_anim.setDuration(260)
        self.slide_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.slide_out_anim = QPropertyAnimation(self, b"pos", self)
        self.slide_out_anim.setDuration(220)
        self.slide_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)

        self._final_pos = QPoint()
        self._closed_callback = None

        self.slide_out_anim.finished.connect(self._on_close_finished)

    def set_closed_callback(self, callback):
        self._closed_callback = callback

    def show_toast(self, final_pos: QPoint, timeout_ms: int = 4000):
        self._final_pos = QPoint(final_pos)
        start_pos = QPoint(final_pos.x(), final_pos.y() + 24)

        self.move(start_pos)
        self.show()
        self.raise_()

        self.fade_in_anim.start()

        self.slide_in_anim.stop()
        self.slide_in_anim.setStartValue(start_pos)
        self.slide_in_anim.setEndValue(final_pos)
        self.slide_in_anim.start()

        QTimer.singleShot(max(500, int(timeout_ms)), self.start_close)

    def start_close(self):
        if not self.isVisible():
            return

        self.fade_out_anim.start()

        end_pos = QPoint(self._final_pos.x(), self._final_pos.y() + 16)
        self.slide_out_anim.stop()
        self.slide_out_anim.setStartValue(self.pos())
        self.slide_out_anim.setEndValue(end_pos)
        self.slide_out_anim.start()

    def _on_close_finished(self):
        self.close()
        if callable(self._closed_callback):
            self._closed_callback(self)
        self.deleteLater()


class NotificationManager:
    """
    Custom in-app toast manager.

    Features:
    - queue
    - stacked toasts
    - max 1 new toast per 5 seconds
    - fade-in / fade-out
    - slide-in from bottom
    """

    MIN_INTERVAL_MS = 1500
    DEFAULT_TIMEOUT_MS = 5000
    STACK_SPACING = 10
    SCREEN_MARGIN = 20
    MAX_VISIBLE = 4

    def __init__(self, parent: QWidget | None = None):
        self.parent = parent
        self._queue = deque()
        self._visible_toasts: list[ToastPopup] = []
        self._cooldown = False

    def show_toast(self, title: str, message: str, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        payload = (str(title), str(message), int(timeout_ms))
        self._queue.append(payload)
        self._try_show_next()

    def _try_show_next(self):
        if self._cooldown:
            return

        if not self._queue:
            return

        if len(self._visible_toasts) >= self.MAX_VISIBLE:
            return

        title, message, timeout_ms = self._queue.popleft()

        toast = ToastPopup(title=title, message=message, parent=self.parent)
        toast.set_closed_callback(self._on_toast_closed)

        self._visible_toasts.append(toast)
        self._reposition_visible_toasts(animated=False)

        final_pos = self._compute_toast_pos(len(self._visible_toasts) - 1, toast.height())
        toast.show_toast(final_pos=final_pos, timeout_ms=timeout_ms)

        self._start_cooldown()

    def _on_toast_closed(self, toast: ToastPopup):
        if toast in self._visible_toasts:
            self._visible_toasts.remove(toast)

        self._reposition_visible_toasts(animated=True)
        self._try_show_next()

    def _start_cooldown(self):
        self._cooldown = True
        QTimer.singleShot(self.MIN_INTERVAL_MS, self._end_cooldown)

    def _end_cooldown(self):
        self._cooldown = False
        self._try_show_next()

    def _reposition_visible_toasts(self, animated: bool):
        for index, toast in enumerate(self._visible_toasts):
            target = self._compute_toast_pos(index, toast.height())

            if not animated or not toast.isVisible():
                toast.move(target)
                continue

            anim = QPropertyAnimation(toast, b"pos", toast)
            anim.setDuration(180)
            anim.setStartValue(toast.pos())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()

            # obdrži referenco, da animacija ne umre takoj
            toast._stack_move_anim = anim

    def _compute_toast_pos(self, stack_index: int, toast_height: int) -> QPoint:
        screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(100, 100)

        geometry = screen.availableGeometry()

        x = geometry.right() - 320 - self.SCREEN_MARGIN
        y = (
            geometry.bottom()
            - toast_height
            - self.SCREEN_MARGIN
            - stack_index * (toast_height + self.STACK_SPACING)
        )

        return QPoint(x, y)