"""Отдельная служба воспроизведения для GUI-сборки."""
from __future__ import annotations

import sys

import main


def run() -> int:
    if "--tray" in sys.argv:
        return main.main(["--backend", "trcc"])
    return main.main(
        ["--backend", "trcc", "--no-tray", "--allow-offline"]
    )


if __name__ == "__main__":
    raise SystemExit(run())
