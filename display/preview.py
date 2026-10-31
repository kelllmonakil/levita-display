"""Бэкенд-заглушка: окно предпросмотра на ПК с маской видимой области.

Поток планировщика кладёт кадры в ``send_frame``; окно Qt живёт в главном
потоке и перерисовывается по таймеру. Так декодирование GIF не блокирует UI.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

from PIL import Image

from display.base import DisplayBackend

log = logging.getLogger(__name__)


class PreviewBackend(DisplayBackend):
    def __init__(
        self,
        size: tuple[int, int],
        scale: float = 0.55,
        corner_radius: int = 40,
        show_mask: bool = True,
    ) -> None:
        self._size = size
        self._scale = max(0.2, min(1.0, scale))
        self._corner_radius = max(0, corner_radius)
        self._show_mask = show_mask

        self._lock = threading.Lock()
        self._frame: Image.Image | None = None
        self._status = ""
        self._frames = 0
        self._fps = 0.0
        self._fps_t0 = time.monotonic()
        self._fps_count = 0

        self._app = None
        self._window = None
        self.on_toggle_pause = None
        self.on_next = None

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    # ── приём кадров из потока планировщика ────────────────────────────

    def send_frame(self, rgb_image: Image.Image) -> None:
        if rgb_image.size != self._size:
            rgb_image = rgb_image.resize(self._size, Image.BILINEAR)
        with self._lock:
            self._frame = rgb_image.convert("RGB")
            self._frames += 1
            self._fps_count += 1
            now = time.monotonic()
            elapsed = now - self._fps_t0
            if elapsed >= 1.0:
                self._fps = self._fps_count / elapsed
                self._fps_count = 0
                self._fps_t0 = now

    def set_status(self, text: str) -> None:
        with self._lock:
            self._status = text

    def get_latest(self) -> Image.Image | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stats(self) -> tuple[float, int]:
        with self._lock:
            return self._fps, self._frames

    # ── окно ──────────────────────────────────────────────────────────

    def run(
        self,
        screenshot_after_ms: int | None = None,
        screenshot_path: str | None = None,
    ) -> None:
        """Показать окно и работать до закрытия (блокирует поток).

        ``screenshot_after_ms``/``screenshot_path`` — служебный режим: снять
        окно и выйти, чтобы проверять вёрстку без человека за экраном.
        """
        from PySide6 import QtCore, QtGui, QtWidgets

        self._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        self._window = _make_window(self)
        self._window.setWindowTitle(
            f"Levita preview — {self._size[0]}x{self._size[1]} (маска условная)"
        )
        w = int(self._size[0] * self._scale)
        h = int(self._size[1] * self._scale)
        self._window.resize(w + 20, h + 40)

        timer = QtCore.QTimer()
        timer.timeout.connect(self._window.update)
        timer.start(16)

        self._window.show()
        if screenshot_after_ms is not None and screenshot_path:
            def _shot() -> None:
                self._window.grab().save(screenshot_path)
                log.info("скриншот предпросмотра: %s", screenshot_path)
                self._app.quit()

            QtCore.QTimer.singleShot(screenshot_after_ms, _shot)
        self._app.exec()
        log.info("окно предпросмотра закрыто")

    def close(self) -> None:
        if self._app is not None:
            self._app.quit()


def _make_window(backend: PreviewBackend):
    """Создаёт QWidget после того, как QApplication уже существует."""
    from PySide6 import QtCore, QtGui, QtWidgets

    class Window(QtWidgets.QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.show_mask = backend._show_mask
            self.setStyleSheet("background:#111;")
            self.setFocusPolicy(QtCore.Qt.StrongFocus)

        def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
            key = event.key()
            if key in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Q):
                self.close()
            elif key == QtCore.Qt.Key_Space and backend.on_toggle_pause:
                backend.on_toggle_pause()
            elif key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_N) and backend.on_next:
                backend.on_next()
            elif key == QtCore.Qt.Key_M:
                self.show_mask = not self.show_mask
            elif key == QtCore.Qt.Key_F:
                if self.isFullScreen():
                    self.showNormal()
                else:
                    self.showFullScreen()

        def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
            backend.close()
            super().closeEvent(event)

        def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
            painter = QtGui.QPainter(self)
            painter.fillRect(self.rect(), QtGui.QColor("#0b0b0b"))

            frame = backend.get_latest()
            if frame is None:
                painter.end()
                return

            cw, ch = backend.size
            aw = self.width()
            ah = self.height() - 26
            scale = min(aw / cw, ah / ch)
            dw, dh = int(cw * scale), int(ch * scale)
            ox = (aw - dw) // 2
            oy = 26 + (ah - dh) // 2

            img = frame.convert("RGB")
            qimg = QtGui.QImage(
                img.tobytes(), cw, ch, cw * 3, QtGui.QImage.Format_RGB888
            ).copy()

            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            target = QtCore.QRect(ox, oy, dw, dh)
            painter.drawImage(target, qimg)

            # Маска видимой области: затемняем то, что панель не показывает.
            if self.show_mask:
                radius = backend._corner_radius * scale
                path = QtGui.QPainterPath()
                path.addRoundedRect(QtCore.QRectF(ox, oy, dw, dh), radius, radius)
                outside = QtGui.QPainterPath()
                outside.addRect(QtCore.QRectF(ox, oy, dw, dh))
                outside = outside.subtracted(path)
                painter.fillPath(outside, QtGui.QColor(0, 0, 0, 190))
                painter.setPen(
                    QtGui.QPen(QtGui.QColor(120, 180, 255, 140), 1, QtCore.Qt.DashLine)
                )
                painter.drawPath(path)
            else:
                painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90), 1))
                painter.drawRect(target)

            fps, total = backend.stats()
            hud = f"{fps:5.1f} fps   {total} кадров   {backend._status}"
            painter.setPen(QtGui.QColor("#9ad"))
            painter.drawText(8, 18, hud)

            painter.end()

    return Window()
