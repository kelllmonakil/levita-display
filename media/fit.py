"""Подгонка кадра под холст.

Правило: если обрезка по центру теряет не больше ``crop_tolerance`` площади
кадра — обрезаем (картинка заполняет экран целиком). Иначе вписываем кадр
целиком, а поля заполняем размытым увеличенным фоном из этого же кадра.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter
from collections import OrderedDict


@dataclass(frozen=True)
class FitPlan:
    mode: str                      # "crop" | "blur_fill"
    src_size: tuple[int, int]
    canvas: tuple[int, int]
    crop_box: tuple[int, int, int, int] | None
    loss: float                    # доля площади, потерянной при обрезке

    def apply(
        self,
        frame: Image.Image,
        blur_radius: int = 32,
        blur_darken: float = 0.55,
    ) -> Image.Image:
        if frame.size != self.src_size:
            frame = frame.resize(self.src_size, Image.BILINEAR)
        if frame.mode != "RGB":
            frame = frame.convert("RGB")

        if self.mode == "crop" and self.crop_box is not None:
            return frame.crop(self.crop_box).resize(self.canvas, Image.BILINEAR)

        # Размытый фон: считаем его вчетверо меньше и растягиваем — на глаз
        # неотличимо от полного разрешения, но в разы дешевле по CPU.
        cw, ch = self.canvas
        small = frame.resize((max(1, cw // 4), max(1, ch // 4)), Image.BILINEAR)
        bg = small
        if blur_radius > 0:
            bg = bg.filter(ImageFilter.GaussianBlur(max(1.0, blur_radius / 4)))
        bg = bg.resize(self.canvas, Image.BILINEAR)
        if blur_darken < 1.0:
            bg = ImageEnhance.Brightness(bg).enhance(max(0.0, blur_darken))

        fg = _contain(frame, self.canvas)
        x = (cw - fg.width) // 2
        y = (ch - fg.height) // 2
        bg.paste(fg, (x, y))
        return bg


def _contain(frame: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    cw, ch = canvas
    sw, sh = frame.size
    scale = min(cw / sw, ch / sh)
    size = (max(1, round(sw * scale)), max(1, round(sh * scale)))
    return frame.resize(size, Image.BILINEAR)


def crop_loss(src: tuple[int, int], canvas: tuple[int, int]) -> float:
    """Какая доля площади кадра пропадёт при обрезке «вписать по покрытию»."""
    sw, sh = src
    cw, ch = canvas
    if min(sw, sh, cw, ch) <= 0:
        return 1.0
    scale = max(cw / sw, ch / sh)
    kept_w = min(sw, cw / scale)
    kept_h = min(sh, ch / scale)
    return max(0.0, 1.0 - (kept_w * kept_h) / (sw * sh))


def plan_fit(
    src_size: tuple[int, int],
    canvas: tuple[int, int],
    tolerance: float = 0.18,
    focus: tuple[float, float] | None = None,
) -> FitPlan:
    """Решает, обрезать или вписывать. ``focus`` — центр интереса (0..1)."""
    sw, sh = src_size
    cw, ch = canvas
    if min(sw, sh, cw, ch) <= 0:
        return FitPlan("blur_fill", src_size, canvas, None, 1.0)

    loss = crop_loss(src_size, canvas)
    if loss <= tolerance:
        scale = max(cw / sw, ch / sh)
        box_w = min(sw, round(cw / scale))
        box_h = min(sh, round(ch / scale))
        fx, fy = focus if focus else (0.5, 0.5)
        left = round(fx * sw - box_w / 2)
        top = round(fy * sh - box_h / 2)
        left = max(0, min(sw - box_w, left))
        top = max(0, min(sh - box_h, top))
        return FitPlan("crop", src_size, canvas, (left, top, left + box_w, top + box_h), loss)

    return FitPlan("blur_fill", src_size, canvas, None, loss)


class FitCache:
    """Кэш решений подгонки: план зависит только от размера источника и настроек."""
    def __init__(self, canvas: tuple[int, int], tolerance: float) -> None:
        self._canvas = canvas
        self._tolerance = tolerance
        self._by_size: dict[tuple[int, int], FitPlan] = {}
        self._by_path: dict[tuple[str, float], FitPlan] = {}

    def for_size(self, src_size: tuple[int, int]) -> FitPlan:
        plan = self._by_size.get(src_size)
        if plan is None:
            plan = plan_fit(src_size, self._canvas, self._tolerance)
            self._by_size[src_size] = plan
        return plan

    def for_path(self, path: Path | str, mtime: float, src_size: tuple[int, int]) -> FitPlan:
        key = (str(path), mtime)
        plan = self._by_path.get(key)
        if plan is None:
            plan = self.for_size(src_size)
            self._by_path[key] = plan
        return plan

    def clear(self) -> None:
        self._by_size.clear()
        self._by_path.clear()


class FittedFrameCache:
    """LRU готовых кадров холста.

    Короткий GIF после первого круга проигрывается без resize/fit — это
    заметно снижает CPU на 60 fps. Длинные ролики вытесняют старые кадры,
    поэтому памяти больше ``max_mb`` не занимаем.
    """

    def __init__(self, max_mb: int = 160) -> None:
        self.max_bytes = max(16, max_mb) * 1024 * 1024
        self._items: "OrderedDict[tuple, Image.Image]" = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> Image.Image | None:
        image = self._items.get(key)
        if image is None:
            self.misses += 1
            return None
        self._items.move_to_end(key)
        self.hits += 1
        return image

    def put(self, key: tuple, image: Image.Image) -> None:
        if key in self._items:
            return
        cost = image.width * image.height * 3
        if cost > self.max_bytes:
            return
        while self._bytes + cost > self.max_bytes and self._items:
            _, old = self._items.popitem(last=False)
            self._bytes -= old.width * old.height * 3
        self._items[key] = image
        self._bytes += cost

    @property
    def frames(self) -> int:
        return len(self._items)

    @property
    def megabytes(self) -> float:
        return self._bytes / (1024 * 1024)
