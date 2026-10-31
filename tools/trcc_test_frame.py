"""Первый тест экрана: сплошной цвет N секунд (с keepalive).

Запуск: .venv\\Scripts\\python tools\\trcc_test_frame.py ff0000 5
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from display.trcc_backend import TrccBackend, TrccDisplayError  # noqa: E402


def parse_color(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    if len(text) != 6:
        raise argparse.ArgumentTypeError("цвет в формате RRGGBB")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("color", type=parse_color, nargs="?", default=(255, 0, 0))
    parser.add_argument("seconds", type=float, nargs="?", default=5.0)
    parser.add_argument("--hz", type=float, default=3.0)
    args = parser.parse_args()

    backend = TrccBackend()
    try:
        backend.connect()
    except TrccDisplayError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1

    frame = Image.new("RGB", backend.size, args.color)
    sent = 0
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.seconds:
            t0 = time.perf_counter()
            backend.send_frame(frame)
            sent += 1
            print(
                f"кадр {sent}: {(time.perf_counter() - t0) * 1000:.1f} мс",
                flush=True,
            )
            time.sleep(1.0 / max(0.5, args.hz))
    finally:
        backend.close()
    print(f"отправлено кадров: {sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
