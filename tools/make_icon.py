"""Рисует иконку приложения (PNG и ICO) без внешних ассетов."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets"


def main() -> int:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Мягкое свечение: несколько полупрозрачных кругов.
    for radius, alpha in ((120, 60), (96, 90), (72, 130)):
        d.ellipse(
            (size // 2 - radius, size // 2 - radius,
             size // 2 + radius, size // 2 + radius),
            fill=(70, 190, 255, alpha),
        )
    glow = img.filter(ImageFilter.GaussianBlur(12))

    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(base)
    bd.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(18, 18, 30, 255))
    bd.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, outline=(90, 200, 255, 200), width=4)

    # Буква L и «волна» цвета.
    bd.rounded_rectangle((78, 68, 106, 190), radius=10, fill=(240, 248, 255, 255))
    bd.rounded_rectangle((78, 162, 182, 190), radius=10, fill=(240, 248, 255, 255))
    bd.ellipse((150, 70, 186, 106), fill=(255, 90, 190, 255))
    bd.ellipse((168, 120, 196, 148), fill=(255, 200, 70, 255))

    out = Image.alpha_composite(base, glow)
    out.alpha_composite(base)

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "icon.png"
    ico = OUT / "icon.ico"
    out.save(png)
    out.save(ico, sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256)])
    print(f"{png}\n{ico}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
