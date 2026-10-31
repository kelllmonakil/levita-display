"""Создаёт короткий тестовый MP4 (для проверки видео-плеера)."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".cache/test_video.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps, seconds = 1600, 720, 30, 4
    writer = cv2.VideoWriter(
        str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        print("OpenCV не смог создать MP4", file=sys.stderr)
        return 1
    yy, xx = np.mgrid[0:height, 0:width]
    for i in range(fps * seconds):
        t = i / fps
        hue = (xx / width + t * 0.25) % 1.0
        r = (np.sin(hue * 6.28) * 0.5 + 0.5) * 255
        g = (np.sin(hue * 6.28 + 2.1) * 0.5 + 0.5) * 255
        b = (np.sin(hue * 6.28 + 4.2) * 0.5 + 0.5) * 255
        frame = np.stack([b, g, r], axis=-1).astype(np.uint8)
        writer.write(frame)
    writer.release()
    print(f"{out} ({out.stat().st_size // 1024} КБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
