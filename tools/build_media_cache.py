"""Один раз собирает кэш воспроизведения для всех крупных GIF/видео."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config  # noqa: E402
from media.library import GifLibrary  # noqa: E402
from media.transcode import MediaCache  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    cfg = load_config("config.toml")
    cache = MediaCache(ROOT, cfg.display.width, cfg.display.height)
    library = GifLibrary(
        ROOT / cfg.media.folder, cache_dir=ROOT / ".cache", media_cache=cache
    )
    entries = library.scan()
    todo = [e for e in entries if cache.should_transcode(e)]
    print(f"файлов: {len(entries)}, требуют кэша: {len(todo)}")
    for entry in todo:
        started = time.monotonic()
        cached = cache.ensure(entry)
        changed = cached.path != entry.path
        print(
            f"  {entry.name}: {'кэш' if changed else 'оригинал'} "
            f"{cached.width}x{cached.height}, "
            f"{(time.monotonic() - started):.1f} с"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
