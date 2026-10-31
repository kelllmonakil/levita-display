"""Симуляция палитры во времени: какие цвета ушли бы в ARGB и когда."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from core.config import load_config  # noqa: E402
from media.fit import plan_fit  # noqa: E402
from media.palette import PaletteTracker, dominant_colors  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else next(
        iter(sorted(Path("gifs").glob("*.gif"))), None
    )
    if path is None:
        print("нет GIF в gifs/")
        return 1
    cfg = load_config("config.toml")
    tracker = PaletteTracker(cfg.palette.smoothing)
    with Image.open(path) as im:
        total = max(1, getattr(im, "n_frames", 1))
        delay = max(0.02, (im.info.get("duration") or 100) / 1000.0)
        frames = []
        for index in range(total):
            im.seek(index)
            frame = im.convert("RGB")
            plan = plan_fit(frame.size, cfg.display.size, cfg.media.crop_tolerance)
            frames.append(plan.apply(frame, cfg.media.blur_radius, cfg.media.blur_darken))
    print(f"кадров {total}, задержка {delay*1000:.0f} мс, круг {total*delay:.1f} с")

    now = 0.0
    last_sample = -1.0
    last_color = None
    for loop in range(2):
        for index, fitted in enumerate(frames):
            now += delay
            if now - last_sample >= cfg.palette.sample_seconds:
                tracker.update(dominant_colors(fitted, cfg.palette.colors))
                last_sample = now
            color = tracker.accent_stable(now)
            if color != last_color:
                print(f"{now:5.2f} с, кадр {index:2d}: #{color[0]:02x}{color[1]:02x}{color[2]:02x}")
                last_color = color
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
