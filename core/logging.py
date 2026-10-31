"""Логирование: консоль + вращающийся файл."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import LoggingConfig


def setup_logging(cfg: LoggingConfig, project_root: Path | None = None) -> logging.Logger:
    root = project_root or Path.cwd()
    log_path = Path(cfg.file)
    if not log_path.is_absolute():
        log_path = root / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, cfg.level.upper(), logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(level)

    # Повторная настройка (тесты, перезапуск) не должна плодить хендлеры.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logging.getLogger("levita").debug("логирование включено: %s", log_path)
    return logging.getLogger("levita")
