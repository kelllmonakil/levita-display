"""Проверка управления ARGB: красный -> зелёный -> синий -> белый.

Меняет только цвет, режим не трогает (Direct уже активен). После теста
оставляет белый — дальше приложение перекрасит под палитру.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config  # noqa: E402
from rgb.openrgb_client import OpenRgbClient  # noqa: E402

COLORS = [
    ("красный", (255, 0, 0)),
    ("зелёный", (0, 255, 0)),
    ("синий", (0, 0, 255)),
    ("белый", (255, 255, 255)),
]


def main() -> int:
    cfg = load_config("config.toml")
    client = OpenRgbClient(cfg.rgb.host, cfg.rgb.port)
    client.connect()
    devices = client.list_devices(refresh=True)
    if not devices:
        print("OpenRGB не видит ни одного устройства", file=sys.stderr)
        return 1

    for device in devices:
        zones = [z for z in device.zones if cfg.rgb.zone.lower() in z.name.lower()]
        if not zones:
            print(f"{device.name}: нет зон с '{cfg.rgb.zone}'", file=sys.stderr)
            continue
        for zone in zones:
            if zone.leds_count != cfg.rgb.zone_leds:
                client.resize_zone(device, zone.index, cfg.rgb.zone_leds)
        print(
            f"{device.name}: зоны "
            + ", ".join(f"{z.name} ({cfg.rgb.zone_leds} LED)" for z in zones)
        )
        client.set_custom_mode(device)
        for name, color in COLORS:
            print(f"  -> {name} {color}")
            client.set_color(device, color, zone_fallback=cfg.rgb.zone_leds)
            time.sleep(2.0)
    client.close()
    print("готово: оставлен белый")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
