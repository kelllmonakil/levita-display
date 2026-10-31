"""Служба воспроизведения внутри GUI: старт/стоп и прямой статус."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from core.config import Config
from core.scheduler import Scheduler
from display.trcc_backend import TrccBackend
from media.library import GifLibrary
from media.transcode import MediaCache
from rgb.conflicts import ConflictGuard
from rgb.openrgb_client import FanSyncService

log = logging.getLogger(__name__)


class ServiceRunner:
    def __init__(self, cfg: Config, root: Path) -> None:
        self.cfg = cfg
        self.root = root
        self.backend: TrccBackend | None = None
        self.scheduler: Scheduler | None = None
        self.rgb: FanSyncService | None = None
        self.guard: ConflictGuard | None = None
        self.thread: threading.Thread | None = None
        self.error = ""

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self.error = ""
        backend = TrccBackend()
        try:
            backend.connect()
        except Exception as exc:
            self.error = str(exc)
            log.warning("экран не отвечает при старте: %s", exc)

        folder = Path(self.cfg.media.folder)
        if not folder.is_absolute():
            folder = self.root / folder
        library = GifLibrary(
            folder,
            cache_dir=self.root / ".cache",
            repeat_avoid=self.cfg.media.repeat_avoid,
            shuffle=self.cfg.media.shuffle,
            media_cache=MediaCache(
                self.root, self.cfg.display.width, self.cfg.display.height
            ),
        )
        rgb = FanSyncService(self.cfg.rgb)
        guard = ConflictGuard(self.cfg.rgb)
        scheduler = Scheduler(backend, library, self.cfg, rgb=rgb)
        rgb.start()
        guard.start()
        thread = threading.Thread(target=scheduler.run, name="playback", daemon=True)
        self.backend, self.scheduler, self.rgb, self.guard = backend, scheduler, rgb, guard
        self.thread = thread
        thread.start()
        log.info("служба запущена (в процессе GUI)")

    def stop(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop()
        if self.rgb is not None:
            self.rgb.stop()
        if self.guard is not None:
            self.guard.stop()
        if self.backend is not None:
            self.backend.close()
        if self.thread is not None:
            self.thread.join(timeout=4.0)
        self.thread = None
        self.scheduler = None
        log.info("служба остановлена")

    def status(self) -> dict[str, object]:
        stats = self.scheduler.stats if self.scheduler is not None else None
        connected = bool(self.backend and self.backend.is_connected)
        color = self.rgb.current if self.rgb is not None else None
        return {
            "running": self.running,
            "connected": connected,
            "fps": stats.fps if stats else 0.0,
            "gif": stats.gif if stats else "",
            "argb": "#%02x%02x%02x" % color if color else "—",
            "error": self.error,
        }
