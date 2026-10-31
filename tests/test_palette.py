from __future__ import annotations

from PIL import Image, ImageDraw

from media.palette import PaletteTracker, dominant_colors, vivid


def _quadrants() -> Image.Image:
    img = Image.new("RGB", (300, 300), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 150, 150), fill=(220, 30, 30))
    d.rectangle((150, 0, 300, 150), fill=(30, 200, 60))
    d.rectangle((0, 150, 150, 300), fill=(40, 60, 230))
    d.rectangle((150, 150, 300, 300), fill=(240, 240, 240))
    return img


def test_dominant_colors_find_known_palette() -> None:
    colors = dominant_colors(_quadrants(), k=4)
    found = [c for c, _ in colors]
    expected = [(220, 30, 30), (30, 200, 60), (40, 60, 230), (240, 240, 240)]
    for want in expected:
        nearest = min(found, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, want)))
        assert sum((a - b) ** 2 for a, b in zip(nearest, want)) ** 0.5 < 45


def test_weights_sum_to_one() -> None:
    colors = dominant_colors(_quadrants(), k=4)
    assert abs(sum(w for _, w in colors) - 1.0) < 0.01


def test_tracker_smooths_small_changes() -> None:
    tracker = PaletteTracker(smoothing=0.25)
    tracker.update([((100, 0, 0), 1.0)])
    tracker.update([((130, 0, 0), 1.0)])
    first = tracker.rgb[0]
    assert 100 < first[0] < 130


def test_tracker_switches_instantly_on_scene_change() -> None:
    tracker = PaletteTracker(smoothing=0.25)
    tracker.update([((0, 0, 0), 1.0)])
    tracker.update([((220, 0, 0), 1.0)])
    assert tracker.rgb[0][0] == 220


def test_accent_does_not_jump_between_palette_colors() -> None:
    tracker = PaletteTracker(smoothing=1.0)
    tracker.update([((230, 30, 30), 1.0)])
    first = tracker.accent_stable(now=0.0)

    tracker.update([((30, 30, 230), 1.0)])   # палитра резко сменилась
    assert tracker.accent_stable(now=0.5, min_hold=2.5) == first

    switched = tracker.accent_stable(now=3.2, min_hold=2.5)
    assert switched != first


def test_accent_skips_black() -> None:
    tracker = PaletteTracker()
    tracker.update([((0, 0, 0), 0.7), ((220, 20, 20), 0.3)])
    red, green, blue = tracker.accent()
    assert red > 150 and blue < 100


def test_accent_mixes_similar_shades() -> None:
    tracker = PaletteTracker()
    tracker.update([((200, 20, 20), 0.5), ((180, 40, 20), 0.4)])
    red, green, _ = tracker.accent()
    assert 150 < red < 230
    assert 10 < green < 70


def test_accent_does_not_mix_different_colors() -> None:
    tracker = PaletteTracker()
    tracker.update([((200, 20, 20), 0.5), ((20, 20, 200), 0.5)])
    red, _, blue = tracker.accent()
    assert red > 150
    assert blue < 120


def test_accent_switches_immediately_after_reset() -> None:
    tracker = PaletteTracker()
    tracker.update([((230, 30, 30), 1.0)])
    tracker.accent_stable(now=0.0)
    tracker.reset()
    tracker.update([((30, 30, 230), 1.0)])
    assert tracker.accent_stable(now=1.0) == tracker.accent()


def test_accent_is_vivid() -> None:
    tracker = PaletteTracker()
    tracker.update([((30, 30, 30), 0.9), ((20, 100, 40), 0.1)])
    r, g, b = tracker.accent()
    from colorsys import rgb_to_hsv

    _, s, v = rgb_to_hsv(r / 255, g / 255, b / 255)
    assert s >= 0.75
    assert v >= 0.4


def test_vivid_keeps_hue() -> None:
    from colorsys import rgb_to_hsv

    h1 = rgb_to_hsv(0.8, 0.2, 0.2)[0]
    h2 = rgb_to_hsv(*(c / 255 for c in vivid((204, 51, 51))))[0]
    assert abs(h1 - h2) < 0.02
