"""Создаёт ярлыки: рабочий стол, меню Пуск и автозапуск (exe-сборка)."""
from __future__ import annotations

from pathlib import Path

import win32com.client

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "LevitaDisplay" / "LevitaDisplay.exe"
SERVICE = ROOT / "dist" / "LevitaDisplay" / "LevitaService.exe"
ICON = ROOT / "dist" / "LevitaDisplay" / "_internal" / "assets" / "icon.ico"
WORKDIR = ROOT / "dist" / "LevitaDisplay"


def make(link: Path, args: str, target: Path | None = None) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(str(link))
    shortcut.TargetPath = str(target or EXE)
    shortcut.Arguments = args
    shortcut.WorkingDirectory = str(WORKDIR)
    shortcut.IconLocation = str(ICON)
    shortcut.Description = "Levita Display"
    shortcut.WindowStyle = 1 if not args else 7
    shortcut.Save()
    print(link)


def main() -> int:
    desktop = Path.home() / "Desktop"
    start_menu = (
        Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows"
        / "Start Menu" / "Programs"
    )
    startup = start_menu / "Startup"
    make(desktop / "Levita Display.lnk", "")
    make(start_menu / "Levita Display.lnk", "")
    make(startup / "Levita Display.lnk", "--tray", SERVICE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
