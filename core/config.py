"""Загрузка и валидация config.toml.

Все поля имеют значения по умолчанию, поэтому конфиг может быть частичным.
TOML читается стандартным tomllib (Python 3.11+) либо tomli на 3.10.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - только для 3.10
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class DisplayConfig:
    width: int = 1600
    height: int = 720
    fps: int = 60
    corner_radius: int = 120
    # "preview" — окно на ПК, "trcc" — реальный экран через trcc-linux.
    backend: str = "preview"
    # Через сколько секунд пробовать снова, если экран отвалился по USB.
    reconnect_seconds: float = 5.0

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


@dataclass
class PreviewConfig:
    scale: float = 0.55
    show_mask: bool = True


@dataclass
class MediaConfig:
    folder: str = "gifs"
    rotation_seconds: float = 20.0
    transition_ms: int = 700
    shuffle: bool = True
    repeat_avoid: int = 6
    crop_tolerance: float = 0.20
    blur_radius: int = 32
    blur_darken: float = 0.55
    # Сколько памяти держать под готовые кадры (ускоряет повторные круги GIF).
    frame_cache_mb: int = 256


@dataclass
class PaletteConfig:
    colors: int = 4
    sample_seconds: float = 0.07
    smoothing: float = 0.6


@dataclass
class RgbConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 6742
    # Подстрока имени устройства OpenRGB; пусто = все устройства со LED.
    device: str = ""
    # Какие зоны платы вести. У MSI это JARGB 1..3 (5V ARGB) и JAF.
    zone: str = "JARGB"
    # Сколько светодиодов на зону: у MSI зоны стартуют с 0 и растягиваются вручную.
    zone_leds: int = 24
    rate_hz: float = 30.0
    # Плавное сглаживание, пока оттенок тот же…
    smooth_seconds: float = 0.6
    # …и быстрое, когда цвет меняется на другой.
    fast_smooth_seconds: float = 0.08
    hue_jump_degrees: float = 35.0
    min_delta: int = 1
    # Закрывать программы, которые перехватывают ARGB (MSI Center, SignalRGB…).
    autokill_conflicts: bool = True
    conflict_check_seconds: float = 10.0


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/levita.log"


@dataclass
class Config:
    display: DisplayConfig = field(default_factory=DisplayConfig)
    preview: PreviewConfig = field(default_factory=PreviewConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    palette: PaletteConfig = field(default_factory=PaletteConfig)
    rgb: RgbConfig = field(default_factory=RgbConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    source: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Path | None = None) -> "Config":
        cfg = cls(source=source)
        _apply(cfg.display, data.get("display"))
        _apply(cfg.preview, data.get("preview"))
        _apply(cfg.media, data.get("media"))
        _apply(cfg.palette, data.get("palette"))
        _apply(cfg.rgb, data.get("rgb"))
        _apply(cfg.logging, data.get("logging"))
        cfg.validate()
        return cfg

    def validate(self) -> None:
        d = self.display
        if d.width <= 0 or d.height <= 0:
            raise ValueError("display.width/height должны быть положительными")
        if not 1 <= d.fps <= 120:
            raise ValueError("display.fps должен быть в диапазоне 1..120")
        if not 0.0 <= self.media.crop_tolerance <= 0.5:
            raise ValueError("media.crop_tolerance должен быть в диапазоне 0..0.5")
        if not 0.0 <= self.palette.smoothing <= 1.0:
            raise ValueError("palette.smoothing должен быть в диапазоне 0..1")
        if self.palette.colors < 1:
            raise ValueError("palette.colors должен быть >= 1")


def _apply(target: Any, data: dict[str, Any] | None) -> None:
    """Копирует известные поля из словаря TOML в dataclass, игнорируя лишние."""
    if not data:
        return
    names = {f.name for f in dataclasses.fields(target)}
    for key, value in data.items():
        if key in names:
            setattr(target, key, value)


def load_config(path: str | Path | None = "config.toml") -> Config:
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        return Config()
    # utf-8-sig: блокнот и PowerShell любят добавлять BOM, TOML его не терпит.
    data = tomllib.loads(p.read_text(encoding="utf-8-sig"))
    return Config.from_dict(data, source=p)
