"""Точка входа: собирает пайплайн и запускает цикл.

Примеры:
    python main.py                       # окно предпросмотра
    python main.py --headless --frames 120 --save-frames .cache/frames
    python main.py --fps 60 --scale 0.7
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.config import load_config
from core.instance import acquire, release
from core.logging import setup_logging
from core.scheduler import Scheduler
from display.headless import HeadlessBackend
from display.preview import PreviewBackend
from media.library import GifLibrary
from media.transcode import MediaCache
from rgb.conflicts import ConflictGuard
from rgb.openrgb_client import FanSyncService

PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
ASSETS_DIR = (
    Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "assets"
    if getattr(sys, "frozen", False)
    else PROJECT_ROOT / "assets"
)
log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Levita Vision 360 — GIF/MP4 и подсветка")
    p.add_argument("--config", default=str(PROJECT_ROOT / "config.toml"))
    p.add_argument("--headless", action="store_true", help="без окна (для замеров)")
    p.add_argument("--backend", choices=["preview", "trcc", "headless"], default=None,
                   help="куда выводить кадры")
    p.add_argument("--frames", type=int, default=None, help="остановиться после N кадров")
    p.add_argument("--save-frames", default=None, help="сохранять каждый 10-й кадр в папку")
    p.add_argument("--fps", type=int, default=None, help="переопределить частоту кадров")
    p.add_argument("--scale", type=float, default=None, help="масштаб окна предпросмотра")
    p.add_argument("--no-rgb", action="store_true", help="не управлять ARGB через OpenRGB")
    p.add_argument("--no-tray", action="store_true", help="без иконки в трее")
    p.add_argument("--allow-offline", action="store_true",
                   help="не выходить, если экран не отвечает при старте")
    p.add_argument("--exit-after", type=float, default=None,
                   help="выйти через N секунд (проверка трея)")
    p.add_argument("--gif-folder", default=None, help="переопределить папку с GIF/MP4")
    p.add_argument("--only", default=None, help="играть только файлы, содержащие подстроку")
    p.add_argument("--rotation-scale", type=float, default=None,
                   help="множитель времени ротации (0.1 = быстрее в 10 раз)")
    p.add_argument("--screenshot", default=None,
                   help="снять окно предпросмотра в файл и выйти")
    p.add_argument("--screenshot-after", type=int, default=1500,
                   help="через сколько мс делать скриншот")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)

    # Windows по умолчанию округляет ожидания до ~15.6 мс — на 60 fps это
    # превращается в рывки. Просим таймер с шагом 1 мс на время работы.
    timer_period = False
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.winmm.timeBeginPeriod(1)
            timer_period = True
        except Exception:  # pragma: no cover - не критично
            pass

    if args.fps:
        cfg.display.fps = args.fps
    if args.scale:
        cfg.preview.scale = args.scale
    if args.gif_folder:
        cfg.media.folder = args.gif_folder
    if args.rotation_scale:
        cfg.media.rotation_seconds = max(0.5, cfg.media.rotation_seconds * args.rotation_scale)
    if args.verbose:
        cfg.logging.level = "DEBUG"

    setup_logging(cfg.logging, PROJECT_ROOT)

    backend_name = args.backend or cfg.display.backend
    if args.headless:
        backend_name = "headless"

    # Экран и ARGB нельзя делить: второй экземпляр сразу выходит.
    lock = None
    if backend_name != "headless":
        lock = acquire(PROJECT_ROOT / ".cache" / "levita.lock")
        if lock is None:
            print(
                "Levita Display уже запущена (или занят lock .cache/levita.lock). "
                "Закройте трей-иконку и повторите.",
                file=sys.stderr,
            )
            return 1

    folder = Path(cfg.media.folder)
    if not folder.is_absolute():
        folder = PROJECT_ROOT / folder

    library = GifLibrary(
        folder,
        cache_dir=PROJECT_ROOT / ".cache",
        repeat_avoid=cfg.media.repeat_avoid,
        shuffle=cfg.media.shuffle,
        only=args.only,
        media_cache=MediaCache(
            PROJECT_ROOT, cfg.display.width, cfg.display.height
        ),
    )
    sensors = None
    overlay = None
    rgb_service = FanSyncService(cfg.rgb)
    conflict_guard = ConflictGuard(cfg.rgb)

    if backend_name == "trcc":
        from display.trcc_backend import TrccBackend

        trcc = TrccBackend()
        try:
            trcc.connect()      # хендшейк; кадры пойдут только из scheduler
        except Exception as exc:
            if args.no_tray and not args.allow_offline:
                print(f"Экран не отвечает: {exc}", file=sys.stderr)
                release(lock)
                return 1
            print(f"Экран не отвечает ({exc}) — запускаюсь и жду переподключения.")
            log.warning("экран не отвечает при старте: %s", exc)
        if trcc.size != (0, 0) and trcc.size != cfg.display.size:
            print(
                f"Внимание: панель {trcc.size[0]}x{trcc.size[1]}, в конфиге "
                f"{cfg.display.width}x{cfg.display.height} — использую панель"
            )
            cfg.display.width, cfg.display.height = trcc.size
        backend = trcc
    elif backend_name == "headless":
        backend = HeadlessBackend(cfg.display.size)
    else:
        backend = PreviewBackend(
            cfg.display.size,
            scale=cfg.preview.scale,
            corner_radius=cfg.display.corner_radius,
            show_mask=cfg.preview.show_mask,
        )

    scheduler = Scheduler(backend, library, cfg, rgb=rgb_service)
    if not args.no_rgb:
        rgb_service.start()
        conflict_guard.start()

    try:
        if backend_name == "trcc" and not args.no_tray:
            from ui.tray import run_tray

            scheduler.start()
            run_tray(
                scheduler,
                backend,
                ASSETS_DIR / "icon.png",
                exit_after_s=args.exit_after,
            )
            scheduler.stop()
        elif isinstance(backend, PreviewBackend):
            backend.on_toggle_pause = scheduler.toggle_pause
            backend.on_next = scheduler.next_gif
            scheduler.start()
            backend.run(
                screenshot_after_ms=args.screenshot_after if args.screenshot else None,
                screenshot_path=args.screenshot,
            )          # блокирует главный поток до закрытия окна
            scheduler.stop()
        else:
            try:
                scheduler.run(max_frames=args.frames, save_dir=args.save_frames)
            except KeyboardInterrupt:
                pass
            if isinstance(backend, HeadlessBackend):
                print(f"кадров: {backend.frames}, средний FPS: {backend.fps:.1f}")
            else:
                print(f"кадров: {scheduler.stats.frames}")
    finally:
        conflict_guard.stop()
        rgb_service.stop()
        backend.close()
        release(lock)
        if timer_period:
            import ctypes

            ctypes.windll.winmm.timeEndPeriod(1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
