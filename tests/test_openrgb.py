from __future__ import annotations

import struct

from core.config import RgbConfig
from rgb.openrgb_client import (
    FanSyncService,
    _distance,
    _hue_delta,
    _lerp,
    _lerp_hsv,
    parse_device,
    update_leds_payload,
    zone_leds_payload,
)


def _text(value: str) -> bytes:
    raw = value.encode() + b"\0"
    return struct.pack("<H", len(raw)) + raw


def _device_data(name: str, zones: list[tuple[str, int]]) -> bytes:
    body = struct.pack("<i", 0) + _text(name) + _text("MSI")
    body += _text("") * 4          # description, version, serial, location
    body += struct.pack("<H", 0)   # modes
    body += struct.pack("<i", 0)   # active mode
    body += struct.pack("<H", len(zones))
    for zone_name, count in zones:
        body += _text(zone_name)
        body += struct.pack("<iIIIH", 1, 0, 240, count, 0)
    body += struct.pack("<H", 0)   # leds
    return struct.pack("<I", len(body) + 4) + body


def test_update_leds_payload_layout() -> None:
    payload = update_leds_payload([(1, 2, 3), (255, 0, 128)])
    size, count = struct.unpack_from("<IH", payload, 0)
    assert size == len(payload)
    assert count == 2
    first, second = struct.unpack_from("<II", payload, 6)
    assert first == 1 | (2 << 8) | (3 << 16)
    assert second == 255 | (0 << 8) | (128 << 16)


def test_zone_payload_layout() -> None:
    payload = zone_leds_payload(2, [(255, 0, 0), (0, 255, 0)])
    size, zone_index, count = struct.unpack_from("<IIH", payload, 0)
    assert size == len(payload)
    assert zone_index == 2
    assert count == 2
    colors = struct.unpack_from("<II", payload, 10)
    assert colors == (255, 255 << 8)


def test_parse_device_reads_zones_when_led_list_empty() -> None:
    data = _device_data("MSI MYSTIC LIGHT", [("JAF", 0), ("JARGB 1", 24), ("JARGB 2", 24)])
    device = parse_device(0, data)
    assert device.name == "MSI MYSTIC LIGHT"
    assert [z.name for z in device.zones] == ["JAF", "JARGB 1", "JARGB 2"]
    assert [z.leds_count for z in device.zones] == [0, 24, 24]
    assert device.led_count == 48       # сумма зон, если общий список пуст
    assert device.mode_name == "?"


def test_parse_device_reads_common_led_list() -> None:
    body = struct.pack("<i", 0) + _text("Board") + _text("Vendor")
    body += _text("") * 4
    body += struct.pack("<H", 0) + struct.pack("<i", 0)
    body += struct.pack("<H", 0)          # zones
    body += struct.pack("<H", 2)          # leds
    body += _text("LED 1") + struct.pack("<I", 0)
    body += _text("LED 2") + struct.pack("<I", 1)
    data = struct.pack("<I", len(body) + 4) + body
    device = parse_device(3, data)
    assert device.index == 3
    assert device.led_count == 2
    assert device.zones == ()


def test_smoothing_helpers() -> None:
    assert _lerp((0, 0, 0), (100, 200, 50), 0.5) == (50, 100, 25)
    assert _lerp((0, 0, 0), (10, 10, 10), 2.0) == (10, 10, 10)
    assert _distance((10, 10, 10), (12, 10, 10)) == 2


def test_hue_delta_is_shortest_path() -> None:
    assert round(_hue_delta((255, 0, 0), (0, 255, 0))) == 120
    assert round(_hue_delta((255, 0, 0), (255, 0, 0))) == 0
    assert round(_hue_delta((255, 0, 0), (255, 0, 30))) <= 8


def test_hsv_interpolation_keeps_saturation() -> None:
    from colorsys import rgb_to_hsv

    mid = _lerp_hsv((255, 0, 0), (0, 255, 0), 0.5)
    _, s, v = rgb_to_hsv(*(c / 255 for c in mid))
    assert s > 0.9            # не серый на полпути, как было бы в RGB
    assert v > 0.9
    assert mid[0] > 100 and mid[1] > 100


def test_disabled_service_does_not_start_thread() -> None:
    service = FanSyncService(RgbConfig(enabled=False))
    service.start()
    assert service._thread is None
    service.stop()
