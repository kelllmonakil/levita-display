"""Кэш воспроизведения: крупные GIF/4K MP4 перекодируются в 1600p MP4.

Декодировать 2400×1080 GIF и 4K-видео на каждом кадре дорого: 84-кадровый GIF
не влезает в кэш кадров, а 4K H.264 даёт ~20–30 мс на кадр. Один раз пережав
источник в H.264 нужной ширины, получаем плавные 60 fps и меньший расход CPU.

Кэш лежит в `.cache/media/`, имя зависит от пути, mtime и ширины. Оригиналы
не меняются; если файл обновился — кэш пересоберётся.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import cv2

from media.library import MediaEntry

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class MediaCache:
    def __init__(
        self,
        root: Path,
        max_width: int,
        max_height: int,
        crf: int = 20,
        preset: str = "veryfast",
    ) -> None:
        self.root = Path(root) / ".cache" / "media"
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_width = max_width
        self.max_height = max_height
        self.crf = crf
        self.preset = preset
        self._ready: dict[str, MediaEntry] = {}

    def should_transcode(self, entry: MediaEntry) -> bool:
        source_pixels = entry.width * entry.height
        canvas_pixels = self.max_width * self.max_height
        if source_pixels > canvas_pixels * 1.02:
            return True
        # Очень длинные GIF тоже выгодно проигрывать как видео, но готовые
        # MP4 в родном разрешении пережимать не нужно.
        return (
            not entry.is_video
            and entry.frames > 150
            and source_pixels > canvas_pixels * 0.4
        )

    def ensure(self, entry: MediaEntry) -> MediaEntry:
        """Вернуть запись для воспроизведения (кэш или оригинал)."""
        key = f"{Path(entry.path).resolve()}|{entry.mtime}|{self.max_width}"
        cached_key = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        cached = self._ready.get(cached_key)
        if cached is not None and Path(cached.path).exists():
            return cached
        if not self.should_transcode(entry):
            return entry

        target = self.root / f"{cached_key}.mp4"
        if not target.exists():
            if not self._transcode(entry, target):
                return entry
        meta = _probe(target)
        if meta is None:
            return entry
        width, height, frames, delay_ms = meta
        result = replace(
            entry,
            path=str(target),
            width=width,
            height=height,
            frames=frames,
            delay_ms=delay_ms,
            mtime=target.stat().st_mtime,
            size_bytes=target.stat().st_size,
        )
        self._ready[cached_key] = result
        return result

    def _transcode(self, entry: MediaEntry, target: Path) -> bool:
        tmp = target.with_suffix(".part.mp4")
        fps = entry.fps if entry.fps > 1 else 30.0
        factor = min(
            1.0, self.max_width / max(1, entry.width), self.max_height / max(1, entry.height)
        )
        target_width = max(2, int(round(entry.width * factor)) & ~1)
        vf = f"scale={target_width}:-2"
        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", entry.path,
            "-vf", vf,
            "-r", f"{fps:.3f}",
            "-c:v", "libx264",
            "-preset", self.preset,
            "-crf", str(self.crf),
            "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart",
            str(tmp),
        ]
        log.info("кэш: перекодирую %s (%.0f fps) — один раз", entry.name, fps)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("ffmpeg недоступен (%s) — играю оригинал", exc)
            return False
        if completed.returncode != 0 or not tmp.exists():
            log.warning(
                "ffmpeg не перекодировал %s: %s",
                entry.name,
                (completed.stderr or "").strip()[:300],
            )
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(target)
        log.info(
            "кэш: %s готов (%d КБ)", target.name, target.stat().st_size // 1024
        )
        return True


def _probe(path: Path) -> tuple[int, int, int, int] | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        return None
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        return None
    return width, height, frames, max(16, int(round(1000.0 / fps)))
