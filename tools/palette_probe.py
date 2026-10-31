"""Диагностика палитры: что видит k-means и какой цвет уходит в ARGB."""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from core.config import load_config  # noqa: E402
from media.fit import plan_fit  # noqa: E402
from media.palette import PaletteTracker, dominant_colors, vivid  # noqa: E402


def sat(rgb):
    return colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[1]


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "gifs/01_neon_waves_2400x1080.gif")
    cfg = load_config("config.toml")
    tracker = PaletteTracker(cfg.palette.smoothing)
    with Image.open(path) as im:
        total = getattr(im, "n_frames", 1)
        step = max(1, total // 10)
        for index in range(0, total, step):
            im.seek(index)
            frame = im.convert("RGB")
            plan = plan_fit(frame.size, cfg.display.size, cfg.media.crop_tolerance)
            fitted = plan.apply(frame, cfg.media.blur_radius, cfg.media.blur_darken)
            colors = dominant_colors(fitted, cfg.palette.colors)
            tracker.update(colors)
            top = max(colors, key=lambda cw: cw[1])
            vividest = max(colors, key=lambda cw: sat(cw[0]) * (0.5 + cw[1]))
            print(f"\nкадр {index}:")
            for color, weight in colors:
                print(f"   #{color[0]:02x}{color[1]:02x}{color[2]:02x} "
                      f"вес {weight:.2f} sat {sat(color):.2f} "
                      f"score {sat(color)*(0.5+weight):.2f}")
            print(f"   по весу: #{top[0][0]:02x}{top[0][1]:02x}{top[0][2]:02x}, "
                  f"по насыщенности: #{vividest[0][0]:02x}{vividest[0][1]:02x}{vividest[0][2]:02x}")
            print(f"   accent_stable -> #{tracker.accent_stable(index * 0.4)[0]:02x}"
                  f"{tracker.accent_stable(index * 0.4)[1]:02x}"
                  f"{tracker.accent_stable(index * 0.4)[2]:02x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
