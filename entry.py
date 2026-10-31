"""Единая точка входа: GUI или служба (для упакованного exe и разработки)."""
from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if "--service" in argv:
        import main as app_main

        try:
            return app_main.main(
                ["--backend", "trcc", "--no-tray", "--allow-offline"]
            )
        except BaseException:
            _write_crash()
            raise
    if "--standalone" in argv:
        import main as app_main

        try:
            return app_main.main(["--backend", "trcc"])
        except BaseException:
            _write_crash()
            raise
    smoke = None
    if "--smoke" in argv:
        index = argv.index("--smoke")
        try:
            smoke = float(argv[index + 1])
        except (IndexError, ValueError):
            smoke = 4.0
    import gui

    return gui.run(smoke_seconds=smoke)


def _write_crash() -> None:
    import traceback
    from pathlib import Path

    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )
    try:
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "logs" / "crash.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
