"""Оценка задержки подсветки относительно экрана по видео.

Берём средний оттенок области вентиляторов (верхние полосы) и экрана помпы,
затем ищем сдвиг, при котором они совпадают лучше всего.
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

import cv2
import numpy as np


def mean_hue(bgr: np.ndarray) -> tuple[float, float, float]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = hsv[..., 0].astype(np.float32) * 2.0       # 0..360
    s = hsv[..., 1].astype(np.float32) / 255.0
    v = hsv[..., 2].astype(np.float32) / 255.0
    weight = s * v
    mask = weight > 0.15
    if not mask.any():
        return 0.0, 0.0, 0.0
    ang = np.deg2rad(h[mask])
    w = weight[mask]
    x = float((np.cos(ang) * w).sum())
    y = float((np.sin(ang) * w).sum())
    hue = np.rad2deg(np.arctan2(y, x)) % 360
    return hue, float(s[mask].mean()), float(v[mask].mean())


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "video_2026-10-31_11-38-36.mp4"
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 60
    rows = []
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % 3 == 0:  # ~20 Гц
            screen = frame[250:470, 500:800]
            fans = frame[40:95, 50:900]
            sh, ss, sv = mean_hue(screen)
            fh, fs, fv = mean_hue(fans)
            rows.append((index / fps, sh, ss, fh, fs))
        index += 1
    cap.release()

    # Оставляем моменты, где обе области цветные.
    good = [r for r in rows if r[2] > 0.25 and r[4] > 0.1]
    if len(good) < 30:
        print("слишком мало цветных кадров")
        return 1

    def score(lag_s: float) -> float:
        diff = []
        for t, sh, _, fh, _ in good:
            past = t - lag_s
            if past < 0:
                continue
            nearest = min(rows, key=lambda r: abs(r[0] - past))
            d = abs((fh - nearest[1] + 180) % 360 - 180)
            diff.append(d)
        return float(np.median(diff)) if diff else 999.0

    print("лаг, с | медианная разница оттенков, °")
    best = (999.0, 0.0)
    for lag in np.arange(0.0, 3.01, 0.2):
        s = score(float(lag))
        print(f"{lag:4.1f} | {s:6.1f}")
        if s < best[0]:
            best = (s, float(lag))
    print(f"\nлучший лаг: {best[1]:.1f} с (разница {best[0]:.0f}°)")

    print("\nвремя | экран hue/sat | вентиляторы hue/sat")
    for t, sh, ss, fh, fs in rows[:: max(1, len(rows) // 24)]:
        print(f"{t:5.1f} | {sh:5.0f} / {ss:.2f} | {fh:5.0f} / {fs:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
