"""Один экземпляр приложения: именованный файловый lock.

Экран и ARGB нельзя делить между двумя копиями, поэтому второй запуск
завершается с понятным сообщением, а не борется за USB.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)

_WINDOWS = sys.platform == "win32"


def acquire(path: Path) -> IO[str] | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        if _WINDOWS:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - Linux/macOS
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def release(handle: IO[str] | None) -> None:
    if handle is None:
        return
    try:
        if _WINDOWS:
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()
