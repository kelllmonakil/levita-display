"""Тестовая сетка на экран: границы, углы, центр, шкалы.

Помогает проверить ориентацию и понять, какая часть холста реально видна.
Запуск: .venv\\Scripts\\python tools\\trcc_grid.py 12
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from display.trcc_backend import TrccBackend, TrccDisplayError  # noqa: E402

FONT_PATH = r"C:\Windows\Fonts\consola.ttf"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default(size=size)


def build_grid(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, (24, 24, 28))
    d = ImageDraw.Draw(img)
    big = _font(44)
    mid = _font(26)
    small = _font(18)

    # Границы холста и вложенные рамки — по ним видно, что обрезается.
    d.rectangle((0, 0, w - 1, h - 1), outline=(0, 255, 0), width=6)
    for inset, color in ((16, (255, 220, 0)), (40, (0, 200, 255)), (80, (255, 0, 200))):
        d.rectangle((inset, inset, w - 1 - inset, h - 1 - inset), outline=color, width=3)

    # Сетка 100 px и подписи по краям.
    for x in range(100, w, 100):
        d.line((x, 0, x, h), fill=(70, 70, 80), width=1)
        d.text((x + 3, 6), str(x), font=small, fill=(160, 160, 170))
    for y in range(100, h, 100):
        d.line((0, y, w, y), fill=(70, 70, 80), width=1)
        d.text((6, y + 2), str(y), font=small, fill=(160, 160, 170))

    # Углы.
    d.text((26, 26), "TL", font=big, fill=(255, 80, 80))
    d.text((w - 90, 26), "TR", font=big, fill=(80, 255, 80))
    d.text((26, h - 80), "BL", font=big, fill=(80, 160, 255))
    d.text((w - 90, h - 80), "BR", font=big, fill=(255, 220, 80))

    # Центр.
    cx, cy = w // 2, h // 2
    d.line((cx - 120, cy, cx + 120, cy), fill=(255, 255, 255), width=3)
    d.line((cx, cy - 120, cx, cy + 120), fill=(255, 255, 255), width=3)
    d.ellipse((cx - 280, cy - 280, cx + 280, cy + 280), outline=(255, 255, 255), width=4)
    d.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=(255, 255, 255))

    # Подписи размера и ориентации.
    label = f"{w}x{h}"
    d.text((cx - 70, 22), label, font=big, fill=(255, 255, 255))
    d.text((cx - 90, h - 64), "Levita Vision 360", font=mid, fill=(230, 230, 230))
    d.text((w // 2 - 30, 90), "TOP", font=mid, fill=(255, 255, 255))
    d.text((w // 2 - 40, h - 110), "BOTTOM", font=mid, fill=(255, 255, 255))
    return img


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("seconds", type=float, nargs="?", default=12.0)
    parser.add_argument("--hz", type=float, default=3.0)
    parser.add_argument("--save", default=".cache/trcc_grid.png")
    args = parser.parse_args()

    backend = TrccBackend()
    try:
        backend.connect()
    except TrccDisplayError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1

    frame = build_grid(backend.size)
    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    frame.save(args.save)
    print(f"эталон сохранён: {args.save}")

    sent = 0
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.seconds:
            backend.send_frame(frame)
            sent += 1
            time.sleep(1.0 / max(0.5, args.hz))
    finally:
        backend.close()
    print(f"сетка отправлена: {sent} раз(а)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
