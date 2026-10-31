"""Бэкенд без экрана: считает кадры и меряет фактический FPS.

Нужен для тестов, замеров и проверки пайплайна без окна.
"""
from __future__ import annotations

import time

from PIL import Image

from display.base import DisplayBackend


class HeadlessBackend(DisplayBackend):
    def __init__(self, size: tuple[int, int]) -> None:
        self._size = size
        self.frames = 0
        self.last_frame: Image.Image | None = None
        self._t0 = time.monotonic()

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def send_frame(self, rgb_image: Image.Image) -> None:
        self.frames += 1
        self.last_frame = rgb_image

    @property
    def fps(self) -> float:
        elapsed = time.monotonic() - self._t0
        return self.frames / elapsed if elapsed > 0 else 0.0
