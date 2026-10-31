"""Панель управления Levita Display.

Служба воспроизведения работает внутри GUI (без дочерних процессов), поэтому
статус точный, а запуск/остановка мгновенные. Автозапуск использует отдельный
LevitaService.exe, если он есть рядом.
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil
from PySide6 import QtCore, QtGui, QtWidgets

from core.config import load_config
from core.runner import ServiceRunner

log = logging.getLogger(__name__)

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, "_MEIPASS", ROOT)) if FROZEN else ROOT
CONFIG = ROOT / "config.toml"
LOG_FILE = ROOT / "logs" / "levita.log"
ICON = BUNDLE / "assets" / "icon.png"
TOOLS = BUNDLE / "tools"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def gifs_folder() -> Path:
    try:
        cfg = load_config(CONFIG)
        folder = Path(cfg.media.folder)
        return folder if folder.is_absolute() else ROOT / folder
    except Exception:
        return ROOT / "gifs"


def run_elevated(script: Path) -> None:
    params = f'-NoProfile -ExecutionPolicy Bypass -File "{script}"'
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe", params, str(ROOT), 1
    )
    if result <= 32:
        log.warning("не удалось запросить права администратора (%s)", result)


def external_service_pids() -> list[psutil.Process]:
    """Только наши службы (LevitaService.exe или python + entry/main)."""
    found = []
    for proc in psutil.process_iter(["cmdline", "name"]):
        if proc.pid == os.getpid():
            continue
        name = (proc.info.get("name") or "").lower()
        args = [str(x) for x in (proc.info.get("cmdline") or [])]
        text = " ".join(args).lower()
        if name.startswith("levitaservice"):
            found.append(proc)
            continue
        exe = Path(args[0]).name.lower() if args else ""
        if exe not in ("python.exe", "pythonw.exe"):
            continue
        script = " ".join(args[1:]).lower()
        if ("main.py" in script or "entry.py" in script) and (
            "--service" in script or "--standalone" in script
        ):
            found.append(proc)
    return found


def stop_external_services() -> None:
    for proc in external_service_pids():
        try:
            for child in proc.children(recursive=True):
                child.terminate()
            proc.terminate()
            proc.wait(timeout=3)
        except psutil.Error:
            try:
                proc.kill()
            except psutil.Error:
                pass


def standalone_command() -> list[str]:
    service = ROOT / "LevitaService.exe"
    if FROZEN and service.exists():
        return [str(service), "--tray"]
    if FROZEN:
        return [sys.executable, "--standalone"]
    pythonw = Path(sys.executable)
    if pythonw.name.lower() == "python.exe":
        pythonw = pythonw.with_name("pythonw.exe")
    return [str(pythonw), "entry.py", "--standalone"]


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config(CONFIG)
        stop_external_services()
        self.runner = ServiceRunner(self.cfg, ROOT)
        self.setWindowTitle("Levita Display")
        self.setWindowIcon(QtGui.QIcon(str(ICON)))
        self.resize(740, 540)
        self.setStyleSheet("""
            QMainWindow { background:#14141c; }
            QLabel { color:#e8e8f0; }
            QLabel#title { font-size:22px; font-weight:600; }
            QLabel#value { font-size:16px; color:#9fe3ff; }
            QPushButton { background:#222234; color:#e8e8f0; border:1px solid #33334a;
                          border-radius:8px; padding:8px 12px; }
            QPushButton:hover { background:#2c2c44; }
            QPushButton#primary { background:#2277cc; border-color:#2f8fe8; font-weight:600; }
            QPushButton#danger { background:#8a2530; border-color:#b03a46; }
            QPlainTextEdit { background:#0d0d14; color:#b9c6d4; border:1px solid #262638;
                             font-family:Consolas; font-size:12px; }
        """)

        central = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        title = QtWidgets.QLabel("Levita Display")
        title.setObjectName("title")
        outer.addWidget(title)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        self.lbl_screen = self._cell("Экран", "—")
        self.lbl_fps = self._cell("Частота", "—")
        self.lbl_file = self._cell("Файл", "—")
        self.lbl_argb = self._cell("Подсветка", "—")
        grid.addWidget(self.lbl_screen, 0, 0)
        grid.addWidget(self.lbl_fps, 0, 1)
        grid.addWidget(self.lbl_file, 1, 0, 1, 2)
        grid.addWidget(self.lbl_argb, 2, 0, 1, 2)
        outer.addLayout(grid)

        buttons = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Запустить")
        self.btn_start.setObjectName("primary")
        self.btn_stop = QtWidgets.QPushButton("Остановить")
        self.btn_stop.setObjectName("danger")
        self.btn_restart = QtWidgets.QPushButton("Перезапустить")
        for button in (self.btn_start, self.btn_stop, self.btn_restart):
            buttons.addWidget(button)
        outer.addLayout(buttons)

        tools = QtWidgets.QGridLayout()
        self.btn_folder = QtWidgets.QPushButton("Папка с GIF/MP4")
        self.btn_settings = QtWidgets.QPushButton("Настройки")
        self.btn_autostart = QtWidgets.QPushButton("Автозапуск")
        self.btn_openrgb = QtWidgets.QPushButton("OpenRGB: сервер")
        self.btn_msi = QtWidgets.QPushButton("Отключить MSI-службы")
        self.btn_logs = QtWidgets.QPushButton("Обновить лог")
        tools.addWidget(self.btn_folder, 0, 0)
        tools.addWidget(self.btn_settings, 0, 1)
        tools.addWidget(self.btn_autostart, 0, 2)
        tools.addWidget(self.btn_openrgb, 1, 0)
        tools.addWidget(self.btn_msi, 1, 1)
        tools.addWidget(self.btn_logs, 1, 2)
        outer.addLayout(tools)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        outer.addWidget(self.log_view, 1)
        self.setCentralWidget(central)

        self.btn_start.clicked.connect(self.start_service)
        self.btn_stop.clicked.connect(self.stop_service)
        self.btn_restart.clicked.connect(self.restart_service)
        self.btn_folder.clicked.connect(lambda: os.startfile(gifs_folder()))
        self.btn_settings.clicked.connect(lambda: os.startfile(CONFIG))
        self.btn_autostart.clicked.connect(self.toggle_autostart)
        self.btn_openrgb.clicked.connect(
            lambda: run_elevated(TOOLS / "install_openrgb_task.ps1")
        )
        self.btn_msi.clicked.connect(
            lambda: run_elevated(TOOLS / "kill_conflicts.ps1")
        )
        self.btn_logs.clicked.connect(self.refresh)

        self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon(str(ICON)), self)
        menu = QtWidgets.QMenu()
        menu.addAction("Открыть", self.show_window)
        menu.addAction("Запустить", self.start_service)
        menu.addAction("Остановить", self.stop_service)
        menu.addSeparator()
        menu.addAction("Выход", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window()
            if reason == QtWidgets.QSystemTrayIcon.Trigger else None
        )
        self.tray.setToolTip("Levita Display")
        self.tray.show()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1200)

        self.start_service()
        self.refresh()

    def _cell(self, title: str, value: str) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        caption = QtWidgets.QLabel(title)
        caption.setStyleSheet("color:#8a8aa0; font-size:12px;")
        number = QtWidgets.QLabel(value)
        number.setObjectName("value")
        layout.addWidget(caption)
        layout.addWidget(number)
        widget.value_label = number  # type: ignore[attr-defined]
        return widget

    @staticmethod
    def _set(widget: QtWidgets.QWidget, text: str) -> None:
        widget.value_label.setText(text)  # type: ignore[attr-defined]

    def refresh(self) -> None:
        status = self.runner.status()
        if not status["running"]:
            screen = "остановлено"
        elif status["connected"]:
            screen = "подключён"
        elif status["error"]:
            screen = "нет связи"
        else:
            screen = "запускается…"
        self._set(self.lbl_screen, screen)
        fps = float(status["fps"] or 0.0)
        self._set(self.lbl_fps, f"{fps:.1f} fps" if fps else "—")
        self._set(self.lbl_file, str(status["gif"] or "—"))
        self._set(self.lbl_argb, str(status["argb"] or "—"))
        self.btn_autostart.setText(
            "Автозапуск: вкл" if self._autostart_link().exists() else "Автозапуск: выкл"
        )
        try:
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
            text = "\n".join(text.splitlines()[-180:])
        except OSError:
            text = ""
        if text and self.log_view.toPlainText() != text:
            self.log_view.setPlainText(text)
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def start_service(self) -> None:
        if not self.runner.running:
            stop_external_services()
            self.runner.start()
        self.refresh()

    def stop_service(self) -> None:
        self.runner.stop()
        self.refresh()

    def restart_service(self) -> None:
        self.runner.stop()
        QtCore.QTimer.singleShot(500, self.start_service)

    def _autostart_link(self) -> Path:
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        return startup / "Levita Display.lnk"

    def toggle_autostart(self) -> None:
        link = self._autostart_link()
        if link.exists():
            link.unlink(missing_ok=True)
        else:
            _create_shortcut(link, standalone_command(), ROOT, ICON)
        self.refresh()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.tray.showMessage("Levita Display", "Свёрнуто в трей.")

    def quit_app(self) -> None:
        self.runner.stop()
        self.tray.hide()
        QtWidgets.QApplication.quit()


def _create_shortcut(link: Path, command: list[str], workdir: Path, icon: Path) -> None:
    import win32com.client

    link.parent.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(link))
    shortcut.TargetPath = command[0]
    shortcut.Arguments = " ".join(f'"{a}"' for a in command[1:])
    shortcut.WorkingDirectory = str(workdir)
    shortcut.IconLocation = str(icon.with_suffix(".ico"))
    shortcut.WindowStyle = 7
    shortcut.Save()


def run(smoke_seconds: float | None = None) -> int:
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Levita Display")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    if smoke_seconds:
        QtCore.QTimer.singleShot(int(smoke_seconds * 1000), window.quit_app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
