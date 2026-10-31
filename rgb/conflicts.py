"""Автокилл программ, которые перехватывают ARGB.

MSI Center/Mystic Light, SignalRGB, iCUE и подобные периодически возвращают
свой цвет. Поток раз в N секунд завершает известные процессы (кроме OpenRGB —
он нам нужен). Службы Windows без прав администратора не остановить: для них
есть tools/kill_conflicts.ps1, запускаемый от администратора.
"""
from __future__ import annotations

import logging
import threading
import time

import psutil

from core.config import RgbConfig

log = logging.getLogger(__name__)

#: exe-имена (в нижнем регистре) программ, которые управляют подсветкой.
CONFLICTS = {
    "msi.centralserver.exe",
    "msi.terminalserver.exe",
    "msi center.exe",
    "msicenter.exe",
    "mystic light.exe",
    "mysticlight.exe",
    "lightkeeper.exe",
    "signalrgb.exe",
    "icue.exe",
    "corsair.service.exe",
    "armourycrate.exe",
    "armoury crate.exe",
    "lighting service.exe",
    "rgbfusion.exe",
    "rgb fusion.exe",
    "gigabyte control center.exe",
    "razer synapse.exe",
    "synapse3.exe",
    "lghub.exe",
    "nzxt cam.exe",
    "masterplus.exe",
}

#: Никого из них не трогаем.
_NEVER = {"openrgb.exe", "python.exe", "pythonw.exe", "explorer.exe"}


class ConflictGuard:
    def __init__(self, cfg: RgbConfig) -> None:
        self.cfg = cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_log: dict[str, float] = {}
        self.killed_total = 0

    def start(self) -> None:
        if not self.cfg.autokill_conflicts:
            return
        self._thread = threading.Thread(
            target=self._loop, name="rgb-conflicts", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        # Дать OpenRGB/нашему RGB-сервису подняться.
        if self._stop.wait(4.0):
            return
        while not self._stop.is_set():
            try:
                self.kill_once()
            except Exception as exc:  # не роняем приложение
                log.debug("конфликты: %s", exc)
            self._stop.wait(max(3.0, self.cfg.conflict_check_seconds))

    def kill_once(self) -> list[str]:
        killed: list[str] = []
        now = time.monotonic()
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if not name or name in _NEVER or name not in CONFLICTS:
                continue
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    proc.kill()
                killed.append(name)
                self.killed_total += 1
                last = self._last_log.get(name, 0.0)
                if now - last > 300.0:
                    log.info("закрыл конфликтующий процесс: %s", name)
                    self._last_log[name] = now
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                last = self._last_log.get(name, 0.0)
                if now - last > 300.0:
                    log.warning("не смог закрыть %s: %s", name, exc)
                    self._last_log[name] = now
        return killed
