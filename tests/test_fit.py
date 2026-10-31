from __future__ import annotations

from PIL import Image

from media.fit import FitCache, crop_loss, plan_fit

CANVAS = (1600, 720)


def test_crop_when_loss_is_small() -> None:
    plan = plan_fit((2000, 1000), CANVAS, tolerance=0.18)
    assert plan.mode == "crop"
    assert plan.loss < 0.18
    left, top, right, bottom = plan.crop_box  # type: ignore[misc]
    assert 0 <= left < right <= 2000
    assert 0 <= top < bottom <= 1000


def test_blur_fill_when_loss_is_big() -> None:
    plan = plan_fit((900, 900), CANVAS, tolerance=0.18)
    assert plan.mode == "blur_fill"
    assert plan.loss > 0.4


def test_exact_aspect_never_loses_anything() -> None:
    assert crop_loss((3200, 1440), CANVAS) < 1e-6
    assert plan_fit((3200, 1440), CANVAS).mode == "crop"


def test_threshold_is_respected() -> None:
    # 1920x1080 -> 20:9 теряет ровно 20% площади.
    loss = crop_loss((1920, 1080), CANVAS)
    assert abs(loss - 0.20) < 0.005
    assert plan_fit((1920, 1080), CANVAS, tolerance=0.25).mode == "crop"
    assert plan_fit((1920, 1080), CANVAS, tolerance=0.15).mode == "blur_fill"


def test_apply_returns_canvas_size_for_both_modes() -> None:
    for size in ((2000, 1000), (900, 900)):
        src = Image.new("RGB", size, (120, 40, 200))
        out = plan_fit(size, CANVAS).apply(src, blur_radius=12, blur_darken=0.5)
        assert out.size == CANVAS
        assert out.mode == "RGB"


def test_blur_fill_has_no_black_bars() -> None:
    src = Image.new("RGB", (800, 900), (200, 30, 30))
    out = plan_fit((800, 900), CANVAS).apply(src, blur_radius=8, blur_darken=0.6)
    # Углы — размытый фон из кадра, а не чёрные поля.
    for xy in ((2, 2), (CANVAS[0] - 3, 2), (2, CANVAS[1] - 3)):
        r, g, b = out.getpixel(xy)
        assert r > 30 and g < 90 and b < 90


def test_focus_stays_inside_source() -> None:
    plan = plan_fit((3000, 1000), CANVAS, tolerance=0.5, focus=(1.0, 0.0))
    left, top, right, bottom = plan.crop_box  # type: ignore[misc]
    assert right <= 3000 and bottom <= 1000
    assert left >= 0 and top >= 0


def test_cache_reuses_plan() -> None:
    cache = FitCache(CANVAS, 0.18)
    first = cache.for_size((900, 900))
    second = cache.for_size((900, 900))
    assert first is second
