"""Каталог локальных GIF и видео: метаданные, кэш, история показов."""
from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
from PIL import Image

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v"}
IMAGE_SUFFIXES = {".gif", ".webp", ".png", ".jpg", ".jpeg", ".bmp"}
SUPPORTED = VIDEO_SUFFIXES | IMAGE_SUFFIXES


@dataclass(frozen=True)
class MediaEntry:
    path: str
    name: str
    width: int
    height: int
    frames: int
    delay_ms: int
    mtime: float
    size_bytes: int

    @property
    def duration_s(self) -> float:
        return max(0.05, self.frames * self.delay_ms / 1000.0)

    @property
    def is_static(self) -> bool:
        return self.frames <= 1

    @property
    def is_video(self) -> bool:
        return Path(self.path).suffix.lower() in VIDEO_SUFFIXES

    @property
    def fps(self) -> float:
        return 1000.0 / self.delay_ms if self.delay_ms > 0 else 10.0


class ClipPlayer:
    """Проигрывает GIF/картинку, декодируя кадры по мере надобности."""

    def __init__(self, entry: MediaEntry) -> None:
        self.entry = entry
        self._im = Image.open(entry.path)
        self._frames = max(1, getattr(self._im, "n_frames", 1))
        self._idx = 0
        self._acc = 0.0
        self._dirty = True
        self._last: Image.Image | None = None

    @property
    def size(self) -> tuple[int, int]:
        return self._im.size

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def index(self) -> int:
        return self._idx

    def advance(self, dt: float) -> None:
        if self._frames <= 1:
            return
        delay = max(0.02, self.entry.delay_ms / 1000.0)
        self._acc += dt
        steps = 0
        while self._acc >= delay and steps < 8:
            self._acc -= delay
            self._idx = (self._idx + 1) % self._frames
            self._dirty = True
            steps += 1
        if steps >= 8:
            self._acc = 0.0

    def frame(self) -> Image.Image:
        if self._last is None or self._dirty:
            self._im.seek(self._idx)
            self._last = self._im.convert("RGB")
            self._dirty = False
        return self._last

    def reset(self) -> None:
        self._idx = 0
        self._acc = 0.0
        self._dirty = True
        self._last = None

    def close(self) -> None:
        try:
            self._im.close()
        except Exception:  # pragma: no cover
            pass


class VideoPlayer:
    """Проигрывает MP4/WebM через OpenCV (ffmpeg внутри колеса)."""

    def __init__(self, entry: MediaEntry) -> None:
        self.entry = entry
        self._cap = cv2.VideoCapture(entry.path)
        if not self._cap.isOpened():
            raise OSError(f"не удалось открыть видео: {entry.path}")
        self._fps = max(1.0, entry.fps)
        self._frames = max(1, entry.frames)
        self._idx = 0
        self._acc = 0.0
        self._last: Image.Image | None = None
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or entry.width
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or entry.height

    @property
    def size(self) -> tuple[int, int]:
        return self._width, self._height

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def index(self) -> int:
        return self._idx

    def advance(self, dt: float) -> None:
        if self._frames <= 1:
            return
        delay = 1.0 / self._fps
        self._acc += dt
        steps = 0
        while self._acc >= delay and steps < 8:
            self._acc -= delay
            self._idx = (self._idx + 1) % self._frames
            self._last = self._read()
            steps += 1
        if steps >= 8:
            self._acc = 0.0

    def frame(self) -> Image.Image:
        if self._last is None:
            self._last = self._read()
        assert self._last is not None
        return self._last

    def _read(self) -> Image.Image:
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if not ok:
            if self._last is not None:
                return self._last
            return Image.new("RGB", self.size, (0, 0, 0))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def reset(self) -> None:
        self._idx = 0
        self._acc = 0.0
        self._last = None
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:  # pragma: no cover
            pass


def _video_meta(path: Path) -> tuple[int, int, int, int]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise ValueError("OpenCV не открыл видео")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 0
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 0
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    finally:
        cap.release()
    if width <= 0 or height <= 0:
        raise ValueError("нет размеров кадра")
    delay_ms = max(16, int(round(1000.0 / max(1.0, fps))))
    return width, height, max(1, frames), delay_ms


class GifLibrary:
    def __init__(
        self,
        folder: str | Path,
        cache_dir: str | Path = ".cache",
        repeat_avoid: int = 6,
        shuffle: bool = True,
        seed: int | None = None,
        only: str | None = None,
        media_cache=None,
    ) -> None:
        self.folder = Path(folder)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "library.json"
        self.history_path = self.cache_dir / "history.json"
        self.repeat_avoid = max(0, repeat_avoid)
        self.shuffle = shuffle
        self.only = only.lower() if only else None
        self._media_cache = media_cache
        self._rng = random.Random(seed)
        self._entries: list[MediaEntry] = []
        self._history: list[str] = []
        self._sequential = 0
        self._load_state()

    # ── каталог ───────────────────────────────────────────────────────

    def scan(self, force: bool = False) -> list[MediaEntry]:
        if not self.folder.exists():
            log.warning("папка с GIF/видео не найдена: %s", self.folder)
            self._entries = []
            return []

        cached = {} if force else self._read_index()
        entries: list[MediaEntry] = []
        files = sorted(
            (p for p in self.folder.rglob("*") if p.suffix.lower() in SUPPORTED),
            key=lambda p: p.name.lower(),
        )
        if self.only:
            files = [p for p in files if self.only in p.name.lower()]
        for path in files:
            try:
                st = path.stat()
            except OSError:
                continue
            key = str(path.resolve())
            hit = cached.get(key)
            if (
                hit
                and abs(hit.get("mtime", 0) - st.st_mtime) < 0.001
                and hit.get("size_bytes") == st.st_size
            ):
                entries.append(MediaEntry(**hit))
                continue
            try:
                if path.suffix.lower() in VIDEO_SUFFIXES:
                    width, height, frames, delay = _video_meta(path)
                    entry = MediaEntry(
                        path=str(path), name=path.name, width=width, height=height,
                        frames=frames, delay_ms=delay,
                        mtime=st.st_mtime, size_bytes=st.st_size,
                    )
                else:
                    with Image.open(path) as im:
                        frames = max(1, getattr(im, "n_frames", 1))
                        delay = int(im.info.get("duration", 100) or 100)
                        entry = MediaEntry(
                            path=str(path), name=path.name,
                            width=im.width, height=im.height,
                            frames=frames, delay_ms=max(20, delay),
                            mtime=st.st_mtime, size_bytes=st.st_size,
                        )
            except Exception as exc:
                log.warning("не удалось прочитать %s: %s", path.name, exc)
                continue
            entries.append(entry)

        self._entries = entries
        self._write_index(entries)
        videos = sum(1 for e in entries if e.is_video)
        log.info(
            "каталог: %d файл(ов), из них видео %d, в %s",
            len(entries), videos, self.folder,
        )
        return entries

    def refresh(self) -> list[MediaEntry]:
        return self.scan(force=False)

    @property
    def entries(self) -> list[MediaEntry]:
        return list(self._entries)

    def pick_next(self, exclude: set[str] | None = None) -> MediaEntry | None:
        if not self._entries:
            return None
        skip = exclude or set()
        alive = [e for e in self._entries if Path(e.path).exists()]
        if len(alive) != len(self._entries):
            self._entries = alive
            if not alive:
                return None
        if not self.shuffle:
            for _ in range(len(self._entries)):
                entry = self._entries[self._sequential % len(self._entries)]
                self._sequential += 1
                if entry.path not in skip:
                    self._remember(entry)
                    return entry
            entry = self._entries[0]
            self._remember(entry)
            return entry

        recent = set(self._history[-self.repeat_avoid:]) if self.repeat_avoid else set()
        pool = [
            e for e in self._entries
            if e.path not in recent and e.path not in skip
        ]
        if not pool:
            pool = [e for e in self._entries if e.path not in skip]
        if not pool:
            pool = self._entries
        entry = self._rng.choice(pool)
        self._remember(entry)
        return entry

    def open(self, entry: MediaEntry) -> ClipPlayer | VideoPlayer:
        if self._media_cache is not None:
            entry = self._media_cache.ensure(entry)
        if entry.is_video:
            return VideoPlayer(entry)
        return ClipPlayer(entry)

    def drop(self, entry: MediaEntry) -> None:
        """Убрать запись о файле, который исчез или не открылся."""
        self._entries = [e for e in self._entries if e.path != entry.path]

    def _remember(self, entry: MediaEntry) -> None:
        self._history.append(entry.path)
        self._history = self._history[-(self.repeat_avoid + 1) * 2:]
        self._save_history()

    # ── состояние на диске ────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._history = [str(x) for x in data]
        except (OSError, ValueError):
            self._history = []

    def _save_history(self) -> None:
        try:
            self.history_path.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            log.debug("не удалось сохранить историю: %s", exc)

    def _read_index(self) -> dict[str, dict]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (OSError, ValueError):
            pass
        return {}

    def _write_index(self, entries: list[MediaEntry]) -> None:
        payload = {e.path: asdict(e) for e in entries}
        try:
            self.index_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError as exc:
            log.debug("не удалось сохранить кэш каталога: %s", exc)
