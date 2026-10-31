"""Проверка экрана без отправки кадров: только хендшейк и чтение профиля.

Запуск: .venv\\Scripts\\python tools\\trcc_connect_check.py
Если TRCC запущен, скрипт скажет об этом и ничего не откроет.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from display.trcc_backend import TrccBackend, TrccDisplayError  # noqa: E402


def main() -> int:
    backend = TrccBackend()
    try:
        backend.connect()
    except TrccDisplayError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    try:
        for key, value in backend.describe().items():
            print(f"{key:18} {value}")
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
