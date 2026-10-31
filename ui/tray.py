"""Иконка в системном трее и меню для ежедневного режима."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def run_tray(
    scheduler,
    backend,
    icon_path: Path,
    window=None,
    exit_after_s: float | None = None,
) -> None:
    """Запускает Qt-цикл с треем. Блокирует поток до «Выход»."""
    from PySide6 import QtCore, QtGui, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Levita Display")
    app.setQuitOnLastWindowClosed(False)

    icon = QtGui.QIcon(str(icon_path))
    if icon.isNull():
        icon = app.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)

    tray = QtWidgets.QSystemTrayIcon(icon)
    tray.setToolTip("Levita Display")
    menu = QtWidgets.QMenu()
    pause_action = menu.addAction("Пауза")
    next_action = menu.addAction("Следующий GIF")
    menu.addSeparator()
    quit_action = menu.addAction("Выход")
    tray.setContextMenu(menu)

    def toggle_pause() -> None:
        scheduler.toggle_pause()
        pause_action.setText("Продолжить" if scheduler.paused.is_set() else "Пауза")

    def next_gif() -> None:
        scheduler.next_gif()

    def quit_app() -> None:
        log.info("выход из приложения")
        tray.hide()
        scheduler.stop()
        backend.close()
        app.quit()

    pause_action.triggered.connect(toggle_pause)
    next_action.triggered.connect(next_gif)
    quit_action.triggered.connect(quit_app)

    def refresh_tooltip() -> None:
        stats = scheduler.stats
        state = "на паузе" if scheduler.paused.is_set() else f"{stats.fps:.0f} fps"
        screen = "экран OK" if backend.is_connected else "экран НЕТ"
        tray.setToolTip(
            f"Levita Display — {state}, {screen}\n{stats.gif}\n"
            f"ARGB #{'%02x%02x%02x' % scheduler.rgb.current if scheduler.rgb else '—'}"
        )

    timer = QtCore.QTimer()
    timer.timeout.connect(refresh_tooltip)
    timer.start(2000)

    tray.show()
    refresh_tooltip()
    log.info("трей: иконка показана")
    if exit_after_s:
        QtCore.QTimer.singleShot(int(exit_after_s * 1000), quit_app)
    app.exec()
    timer.stop()
    tray.hide()
