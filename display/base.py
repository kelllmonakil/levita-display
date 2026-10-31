"""Абстракция вывода на экран.

Всё остальное приложение знает только этот интерфейс, поэтому разработка
идёт без реального устройства: сейчас используется PreviewBackend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image


class DisplayOffline(RuntimeError):
    """Устройство пропало (USB/питание) — бэкенд попробует переподключиться."""


class DisplayBackend(ABC):
    """Куда отправлять готовый кадр."""

    #: Панель возвращается к логотипу без кадров — нужен keepalive на паузе.
    needs_keepalive: bool = False
    #: Подключён ли бэкенд сейчас (для отрисовки статуса и повторов).
    is_connected: bool = True

    def connect(self) -> None:
        """Открыть устройство, если бэкенд этого требует. По умолчанию нечего."""

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]:
        """Размер холста в пикселях (ширина, высота)."""

    @abstractmethod
    def send_frame(self, rgb_image: Image.Image) -> None:
        """Отправить кадр. Изображение в режиме RGB и уже нужного размера."""

    def close(self) -> None:
        """Освободить ресурсы. По умолчанию делать нечего."""
