from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.config import Config, load_config
from media.library import GifLibrary

ROOT = Path(__file__).resolve().parent.parent


def test_project_config_loads() -> None:
    cfg = load_config(ROOT / "config.toml")
    assert cfg.display.size == (1600, 720)
    assert cfg.media.crop_tolerance == pytest.approx(0.20)
    assert Path(cfg.media.folder).name == "gifs"
    assert cfg.rgb.host == "127.0.0.1"


def test_partial_config_uses_defaults() -> None:
    cfg = Config.from_dict({"display": {"fps": 12}})
    assert cfg.display.fps == 12
    assert cfg.display.width == 1600
    assert cfg.media.rotation_seconds == 20


def test_invalid_values_rejected() -> None:
    with pytest.raises(ValueError):
        Config.from_dict({"display": {"fps": 0}})
    with pytest.raises(ValueError):
        Config.from_dict({"media": {"crop_tolerance": 0.9}})


def _write_gif(path: Path, color: tuple[int, int, int]) -> None:
    frames = [Image.new("RGB", (64, 36), color), Image.new("RGB", (64, 36), (10, 10, 10))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=60, loop=0)


def test_library_scans_and_avoids_repeats(tmp_path: Path) -> None:
    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        _write_gif(media_dir / f"clip{i}.gif", color)

    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache", repeat_avoid=2, seed=1)
    entries = lib.scan()
    assert len(entries) == 3
    assert {e.name for e in entries} == {"clip0.gif", "clip1.gif", "clip2.gif"}
    assert all(e.frames == 2 for e in entries)

    picked = [lib.pick_next().name for _ in range(6)]  # type: ignore[union-attr]
    for i in range(len(picked) - 2):
        assert picked[i] not in picked[i + 1:i + 3]

    current = entries[0]
    for _ in range(10):
        nxt = lib.pick_next(exclude={current.path})
        assert nxt is not None
        assert nxt.path != current.path

    player = lib.open(entries[0])
    try:
        frame = player.frame()
        assert frame.size == (64, 36)
        player.advance(0.2)
        assert player.index in (0, 1)
    finally:
        player.close()


def _write_mp4(path: Path, width: int = 128, height: int = 72, frames: int = 6) -> None:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (width, height)
    )
    assert writer.isOpened(), "OpenCV не создал MP4"
    for i in range(frames):
        frame = np.full((height, width, 3), (i * 40) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_media_cache_transcodes_large_video(tmp_path: Path) -> None:
    from media.transcode import MediaCache

    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    _write_mp4(media_dir / "big.mp4", width=320, height=180)
    cache = MediaCache(tmp_path, 128, 128)
    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache", media_cache=cache)
    entry = lib.scan()[0]
    assert cache.should_transcode(entry)
    cached = cache.ensure(entry)
    assert cached.path != entry.path
    assert cached.is_video
    assert cached.width == 128


def test_media_cache_keeps_small_files(tmp_path: Path) -> None:
    from media.transcode import MediaCache

    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    _write_gif(media_dir / "small.gif", (10, 20, 30))
    cache = MediaCache(tmp_path, 1600, 720)
    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache", media_cache=cache)
    entry = lib.scan()[0]
    assert not cache.should_transcode(entry)
    assert cache.ensure(entry).path == entry.path


def test_library_reads_video(tmp_path: Path) -> None:
    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    _write_mp4(media_dir / "clip.mp4")
    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache")
    entries = lib.scan()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.is_video
    assert (entry.width, entry.height) == (128, 72)
    assert entry.frames >= 1

    player = lib.open(entry)
    try:
        frame = player.frame()
        assert frame.size == (128, 72)
        player.advance(0.5)
        assert player.index >= 0
    finally:
        player.close()


def test_library_skips_deleted_files(tmp_path: Path) -> None:
    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    _write_gif(media_dir / "one.gif", (1, 2, 3))
    _write_gif(media_dir / "two.gif", (4, 5, 6))
    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache")
    entries = lib.scan()
    assert len(entries) == 2
    entries[0].path and Path(entries[0].path).unlink()
    entries = lib.scan()
    assert len(entries) == 1
    assert lib.pick_next() is not None


def test_library_cache_file_is_written(tmp_path: Path) -> None:
    media_dir = tmp_path / "gifs"
    media_dir.mkdir()
    _write_gif(media_dir / "one.gif", (1, 2, 3))
    lib = GifLibrary(media_dir, cache_dir=tmp_path / ".cache")
    lib.scan()
    assert (tmp_path / ".cache" / "library.json").exists()

    lib2 = GifLibrary(media_dir, cache_dir=tmp_path / ".cache")
    entries = lib2.scan()
    assert len(entries) == 1
    assert entries[0].name == "one.gif"

