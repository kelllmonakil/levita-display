"""Опрос OpenRGB SDK: список устройств, зон, режимов, числа LED.

Только чтение: ничего не меняет. Запуск:
    .venv\\Scripts\\python tools\\openrgb_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rgb.openrgb_client import OpenRgbClient, OpenRgbError  # noqa: E402


def main() -> int:
    client = OpenRgbClient()
    try:
        client.connect()
        print(f"протокол: {client.protocol}")
        devices = client.list_devices(refresh=True)
        print(f"устройств: {len(devices)}")
        for d in devices:
            print(
                f"\n#{d.index}  {d.name}\n"
                f"    LED: {d.led_count}, зон: {len(d.zones)}, активный режим: "
                f"{d.mode_name!r} [{d.active_mode}]"
            )
            for z in d.zones:
                print(
                    f"    зона {z.index}: {z.name!r} — {z.leds_count} LED "
                    f"(min {z.leds_min}, max {z.leds_max})"
                )
            print("    режимы: " + ", ".join(d.modes))
    except OpenRgbError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
