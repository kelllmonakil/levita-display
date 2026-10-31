"""Замер: декодирование GIF и реальная отправка кадра на экран."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from core.config import load_config  # noqa: E402
from display.trcc_backend import TrccBackend  # noqa: E402
from media.fit import plan_fit  # noqa: E402


def main() -> int:
    cfg = load_config("config.toml")
    path = "gifs/neon_waves.gif"

    # 1. Декодирование кадров GIF.
    with Image.open(path) as im:
        n = getattr(im, "n_frames", 1)
        times = []
        for i in range(min(n, 24)):
            t0 = time.perf_counter()
            im.seek(i)
            frame = im.convert("RGB")
            times.append((time.perf_counter() - t0) * 1000)
    print(f"декод GIF: медиана {statistics.median(times):.2f} мс, "
          f"мин {min(times):.2f}, макс {max(times):.2f}")

    # 2. Подгонка.
    plan = plan_fit(frame.size, cfg.display.size, cfg.media.crop_tolerance)
    fitted = plan.apply(frame, cfg.media.blur_radius, cfg.media.blur_darken)

    # 3. Реальная отправка.
    backend = TrccBackend()
    backend.connect()
    try:
        encode_times, send_times = [], []
        for _ in range(40):
            t0 = time.perf_counter()
            backend.send_frame(fitted)
            send_times.append((time.perf_counter() - t0) * 1000)
    finally:
        backend.close()

    print(f"send_frame всего: медиана {statistics.median(send_times):.2f} мс, "
          f"мин {min(send_times):.2f}, макс {max(send_times):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
