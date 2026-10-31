"""Доминантные цвета кадра и их плавная динамика во времени.

K-means считается по сильно уменьшенному кадру (96x54) в NumPy: это дёшево
и не требует отдельной библиотеки кластеризации. Палитра сглаживается
экспоненциально, чтобы ARGB-вентиляторы не мигали на каждом кадре.
"""
from __future__ import annotations

import colorsys
import random

import numpy as np
from PIL import Image

RGB = tuple[int, int, int]


def _pixels(img: Image.Image, size: tuple[int, int] = (96, 54)) -> np.ndarray:
    small = img.convert("RGB").resize(size, Image.BILINEAR)
    return np.asarray(small, dtype=np.float32).reshape(-1, 3)


def _kmeans(px: np.ndarray, k: int, iterations: int = 12, seed: int = 1234) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    k = max(1, min(k, len(px)))
    centers = [px[rng.integers(len(px))]]
    for _ in range(1, k):
        d2 = np.min(
            ((px[:, None, :] - np.asarray(centers)[None, :, :]) ** 2).sum(axis=2),
            axis=1,
        )
        total = float(d2.sum())
        if total <= 0:
            centers.append(px[rng.integers(len(px))])
            continue
        centers.append(px[rng.choice(len(px), p=d2 / total)])
    centers_arr = np.asarray(centers, dtype=np.float32)

    labels = np.zeros(len(px), dtype=np.int64)
    for _ in range(iterations):
        dist = ((px[:, None, :] - centers_arr[None, :, :]) ** 2).sum(axis=2)
        labels = dist.argmin(axis=1)
        new = centers_arr.copy()
        for i in range(k):
            mask = labels == i
            if mask.any():
                new[i] = px[mask].mean(axis=0)
        if np.allclose(new, centers_arr, atol=0.5):
            centers_arr = new
            break
        centers_arr = new
    counts = np.bincount(labels, minlength=k).astype(np.float32)
    return centers_arr, counts / max(1.0, counts.sum())


def dominant_colors(img: Image.Image, k: int = 4) -> list[tuple[RGB, float]]:
    """Список ``(цвет, вес)``, отсортированный по весу."""
    px = _pixels(img)
    centers, weights = _kmeans(px, k)
    order = np.argsort(weights)[::-1]
    return [
        (tuple(int(round(v)) for v in centers[i]), float(weights[i]))
        for i in order
        if weights[i] > 0
    ]


def _blend(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def _distance(a: RGB, b: RGB) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _accent_score(rgb: RGB) -> float:
    """Яркость важнее площади: светящиеся линии заметнее тёмного фона."""
    r, g, b = (v / 255.0 for v in rgb)
    _, s, v = colorsys.rgb_to_hsv(r, g, b)
    return v * (0.3 + 0.7 * s)


class PaletteTracker:
    """Держит палитру, плавно подтягивая её к новым доминантным цветам."""

    def __init__(self, smoothing: float = 0.25) -> None:
        self.smoothing = max(0.01, min(1.0, smoothing))
        self.colors: list[tuple[RGB, float]] = []
        self._primed = False
        self._accent: RGB | None = None
        self._accent_candidate: RGB | None = None
        self._accent_since = 0.0

    def update(self, fresh: list[tuple[RGB, float]]) -> None:
        if not fresh:
            return
        if not self._primed or len(self.colors) != len(fresh):
            self.colors = list(fresh)
            self._primed = True
            return

        a = self.smoothing
        blended: list[tuple[RGB, float]] = []
        for color, weight in fresh:
            idx = min(
                range(len(self.colors)),
                key=lambda i: _distance(self.colors[i][0], color),
            )
            old_color, old_weight = self.colors[idx]
            # Резкая смена сцены (фиолетовый -> жёлтый): не размазываем цвета,
            # иначе вентиляторы остаются в старом оттенке.
            if _distance(old_color, color) > 45:
                blended.append((color, old_weight + (weight - old_weight) * a))
                continue
            blended.append(
                (_blend(old_color, color, a), old_weight + (weight - old_weight) * a)
            )
        self.colors = blended

    @property
    def rgb(self) -> list[RGB]:
        return [c for c, _ in self.colors]

    def reset(self) -> None:
        """Забыть палитру: при смене ролика сглаживать нечего."""
        self.colors = []
        self._primed = False
        self._accent = None
        self._accent_candidate = None
        self._accent_since = 0.0

    def accent_stable(
        self, now: float, min_hold: float = 0.05, threshold: float = 8.0
    ) -> RGB:
        """Акцентный цвет с гистерезисом: не прыгает между цветами палитры.

        Если самый сочный цвет сменился незначительно — остаёмся на текущем.
        Заметно другой кандидат должен продержаться ``min_hold`` секунд.
        """
        candidate = self.accent()
        if self._accent is None:
            self._accent = candidate
            return candidate
        if _distance(candidate, self._accent) <= threshold:
            self._accent_candidate = None
            return self._accent
        if (
            self._accent_candidate is None
            or _distance(candidate, self._accent_candidate) > threshold
        ):
            self._accent_candidate = candidate
            self._accent_since = now
            return self._accent
        if now - self._accent_since >= min_hold:
            self._accent = candidate
            self._accent_candidate = None
        return self._accent

    def accent(self, index: int = 0) -> RGB:
        """Доминирующий цвет кадра с двумя правилами:

        * почти чёрный пропускается — берём следующий по весу;
        * близкие оттенки смешиваются пропорционально площади.
        """
        if not self.colors:
            return (255, 255, 255)

        visible = [
            (color, weight)
            for color, weight in self.colors
            if max(color) / 255.0 >= 0.12
        ]
        if not visible:
            visible = list(self.colors)
        visible.sort(key=lambda item: item[1], reverse=True)

        base, base_weight = visible[0]
        total = base_weight
        red, green, blue = (channel * base_weight for channel in base)
        for color, weight in visible[1:]:
            if _distance(color, base) > 45:
                break
            red += color[0] * weight
            green += color[1] * weight
            blue += color[2] * weight
            total += weight
        if total <= 0:
            return vivid(base)
        blended = (int(red / total), int(green / total), int(blue / total))
        return vivid(blended)


def _saturation_weight(rgb: RGB) -> float:
    r, g, b = (v / 255.0 for v in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return s * (0.35 + 0.65 * v)


def vivid(rgb: RGB, min_s: float = 0.8, min_v: float = 0.45) -> RGB:
    """Поднимает насыщенность/яркость, чтобы LED не был серым."""
    r, g, b = (v / 255.0 for v in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = max(s, min_s)
    v = max(v, min_v)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def random_color(seed: int | None = None) -> RGB:
    rng = random.Random(seed)
    return (rng.randrange(256), rng.randrange(256), rng.randrange(256))
