"""Главный цикл: кадры с фиксированной частотой, ротация GIF, переходы."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.config import Config
from display.base import DisplayBackend, DisplayOffline
from media.fit import FitCache, FittedFrameCache
from media.library import ClipPlayer, GifLibrary, MediaEntry
from media.palette import PaletteTracker, dominant_colors
from rgb.openrgb_client import FanSyncService

log = logging.getLogger(__name__)


@dataclass
class SchedulerStats:
    frames: int = 0
    fps: float = 0.0
    gif: str = ""
    palette: list[tuple[int, int, int]] | None = None


class Scheduler:
    def __init__(
        self,
        backend: DisplayBackend,
        library: GifLibrary,
        config: Config,
        rgb: FanSyncService | None = None,
    ) -> None:
        self.backend = backend
        self.library = library
        self.cfg = config
        self.rgb = rgb
        self.palette = PaletteTracker(config.palette.smoothing)
        self.stats = SchedulerStats()

        self.stop_event = threading.Event()
        self.paused = threading.Event()
        self._skip = threading.Event()
        self._thread: threading.Thread | None = None
        self._player: ClipPlayer | None = None
        self._last_out: Image.Image | None = None
        self._last_keepalive = 0.0
        self._placeholder_at = 0.0
        self._offline = False
        self._next_reconnect = 0.0
        self._offline_logged = 0.0
        self._reconnect_delay = config.display.reconnect_seconds
        self._on_gif = None

    # ── управление ────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._player is not None:
            self._player.close()
            self._player = None

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()

    def next_gif(self) -> None:
        self._skip.set()

    # ── цикл ──────────────────────────────────────────────────────────

    def run(self, max_frames: int | None = None, save_dir: str | Path | None = None) -> None:
        cfg = self.cfg
        canvas = cfg.display.size
        fit_cache = FitCache(canvas, cfg.media.crop_tolerance)
        frame_cache = FittedFrameCache(cfg.media.frame_cache_mb)

        entries = self.library.scan()
        player = self._next_player()
        player_started = time.monotonic()
        last_tick = player_started
        next_tick = player_started
        frame_dt = 1.0 / cfg.display.fps
        last_palette = 0.0
        transition_start: float | None = None
        prev_plain: Image.Image | None = None
        save_path = Path(save_dir) if save_dir else None
        if save_path:
            save_path.mkdir(parents=True, exist_ok=True)
        frames_since_log = 0
        log_time = last_tick

        while not self.stop_event.is_set():
            now = time.monotonic()
            dt = min(0.25, now - last_tick)
            last_tick = now

            if self.paused.is_set():
                # Панель без кадров возвращается к логотипу: на паузе повторяем
                # последний кадр пару раз в секунду.
                if (
                    getattr(self.backend, "needs_keepalive", False)
                    and self._last_out is not None
                ):
                    now_keepalive = time.monotonic()
                    if now_keepalive - self._last_keepalive >= 0.4:
                        self.backend.send_frame(self._last_out)
                        self._last_keepalive = now_keepalive
                self.stop_event.wait(0.05)
                next_tick = time.monotonic()
                continue

            if player is None:
                self.library.refresh()
                player = self._next_player()
                if player is None:
                    if now - self._placeholder_at >= 2.0:
                        self._run_placeholder(canvas)
                        self._placeholder_at = now
                    self.stop_event.wait(1.0)
                    continue
                player_started = time.monotonic()
                last_tick = player_started
                transition_start = None
                prev_plain = None
                continue

            if self._offline:
                self._try_reconnect(now)
                self.stop_event.wait(0.2)
                continue

            player.advance(dt)
            if player.entry.is_video:
                raw = player.frame()
                plan = fit_cache.for_path(
                    player.entry.path, player.entry.mtime, raw.size
                )
                fitted = plan.apply(
                    raw, cfg.media.blur_radius, cfg.media.blur_darken
                )
            else:
                key = (player.entry.path, player.entry.mtime, player.index, canvas)
                fitted = frame_cache.get(key)
                if fitted is None:
                    raw = player.frame()
                    plan = fit_cache.for_path(
                        player.entry.path, player.entry.mtime, raw.size
                    )
                    fitted = plan.apply(
                        raw, cfg.media.blur_radius, cfg.media.blur_darken
                    )
                    frame_cache.put(key, fitted)

            if now - last_palette >= cfg.palette.sample_seconds:
                self.palette.update(dominant_colors(fitted, cfg.palette.colors))
                self.stats.palette = self.palette.rgb
                if self.rgb is not None:
                    self.rgb.set_target(self.palette.accent_stable(now))
                last_palette = now

            # Переход между GIF: смешиваем сами картинки, а оверлей рисуем
            # один раз поверх — иначе текст на время перехода двоится.
            plain = fitted
            if transition_start is not None and prev_plain is not None:
                alpha = (now - transition_start) / max(0.05, cfg.media.transition_ms / 1000.0)
                if alpha >= 1.0:
                    transition_start = None
                    prev_plain = None
                else:
                    plain = Image.blend(prev_plain, fitted, max(0.0, alpha))

            out = plain

            try:
                self.backend.send_frame(out)
            except DisplayOffline as exc:
                self._offline = True
                self._next_reconnect = now + self._reconnect_delay
                log.warning("экран: %s — жду переподключения", exc)
            else:
                self._last_out = out
                self.stats.frames += 1
                self.stats.gif = player.entry.name
                frames_since_log += 1

            if save_path is not None and self.stats.frames % 10 == 1:
                stem = Path(player.entry.name).stem
                out.save(save_path / f"{stem}_{self.stats.frames:05d}.png")

            rotate = self._skip.is_set() or (
                now - player_started >= cfg.media.rotation_seconds
            )
            if rotate and transition_start is None:
                self._skip.clear()
                self.library.refresh()
                old = player
                new_player = self._next_player()
                if new_player is None:
                    # Все файлы исчезли/битые — не выходим, показываем текущий
                    # кадр и попробуем снова через 5 секунд.
                    player_started = now - cfg.media.rotation_seconds + 5.0
                    log.warning("нет доступных GIF — продолжаю текущий кадр")
                    continue
                prev_plain = fitted
                transition_start = now
                player_started = now
                player = new_player
                old.close()
                self.palette.reset()
                last_palette = 0.0
                log.info(
                    "смена GIF: %s -> %s",
                    old.entry.name,
                    player.entry.name,
                )
                continue

            if now - log_time >= 5.0:
                elapsed = now - log_time
                self.stats.fps = frames_since_log / elapsed
                frames_since_log = 0
                log_time = now
                log.info(
                    "%.1f fps | %s | палитра %s | кэш %d кадр. (%.0f МБ)",
                    self.stats.fps,
                    player.entry.name,
                    " ".join("#%02x%02x%02x" % c for c in self.palette.rgb[:3]),
                    frame_cache.frames,
                    frame_cache.megabytes,
                )
                set_status = getattr(self.backend, "set_status", None)
                if set_status is not None:
                    rgb_text = ""
                    if self.rgb is not None:
                        r, g, b = self.rgb.current
                        rgb_text = (
                            f"  |  ARGB #{r:02x}{g:02x}{b:02x}"
                            + ("" if self.rgb.available else " (нет связи)")
                        )
                    set_status(
                        f"{player.entry.name}  |  палитра "
                        + " ".join("#%02x%02x%02x" % c for c in self.palette.rgb[:3])
                        + rgb_text
                    )

            if max_frames is not None and self.stats.frames >= max_frames:
                break

            next_tick += frame_dt
            sleep = next_tick - time.monotonic()
            if sleep > 0:
                self.stop_event.wait(sleep)
            else:
                # Не копим долг: при перегрузке просто идём дальше.
                next_tick = time.monotonic()

        if player is not None:
            player.close()
            self._player = None

    # ── вспомогательное ───────────────────────────────────────────────

    def _next_player(self) -> ClipPlayer | None:
        current = {self._player.entry.path} if self._player is not None else set()
        for _ in range(3):
            entry: MediaEntry | None = self.library.pick_next(exclude=current)
            if entry is None:
                return None
            try:
                self._player = self.library.open(entry)
                if self._on_gif is not None:
                    self._on_gif(entry)
                return self._player
            except Exception as exc:
                log.warning("не удалось открыть %s: %s", entry.name, exc)
                self.library.drop(entry)
        return None

    def _try_reconnect(self, now: float) -> None:
        if now < self._next_reconnect:
            return
        try:
            self.backend.connect()
        except Exception as exc:
            self._next_reconnect = now + self._reconnect_delay
            # Не долбим панель: 5, 10, 20, 40, максимум 60 секунд.
            self._reconnect_delay = min(60.0, self._reconnect_delay * 2)
            if now - self._offline_logged >= 30.0:
                log.warning("экран: переподключение не удалось (%s)", exc)
                self._offline_logged = now
            return
        self._offline = False
        self._reconnect_delay = self.cfg.display.reconnect_seconds
        self._last_out = None
        log.info("экран: связь восстановлена")

    def _run_placeholder(self, canvas: tuple[int, int]) -> None:
        img = Image.new("RGB", canvas, (12, 12, 16))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 40)
        except OSError:
            font = ImageFont.load_default(size=40)
        text = "Нет GIF: положите файлы в папку media.folder"
        try:
            w = draw.textlength(text, font=font)
        except AttributeError:  # pragma: no cover
            w = len(text) * 20
        draw.text(((canvas[0] - w) / 2, canvas[1] / 2 - 20), text, font=font, fill=(220, 220, 220))
        self.backend.send_frame(img)
        self._last_out = img
        log.warning("в папке нет GIF — показана заглушка")
