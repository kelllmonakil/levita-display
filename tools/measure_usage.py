"""Замер CPU/RAM процесса во время обычной работы (без окна)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    proc = subprocess.Popen(
        [str(PY), "main.py", "--headless", "--fps", "60", "--frames", "1200",
         "--only", "calm_corner"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    p = psutil.Process(proc.pid)

    def app_procs() -> list[psutil.Process]:
        found = []
        for item in psutil.process_iter(["cmdline"]):
            cmd = item.info.get("cmdline") or []
            if any("main.py" in str(part) for part in cmd):
                found.append(item)
        return found

    try:
        time.sleep(4.0)          # прогрев, первый GIF
        procs = app_procs()
        c0 = sum(x.cpu_times().user + x.cpu_times().system for x in procs)
        t0 = time.monotonic()
        time.sleep(8.0)
        procs = app_procs()
        c1 = sum(x.cpu_times().user + x.cpu_times().system for x in procs)
        dt = time.monotonic() - t0
        cpu = (c1 - c0) / dt * 100
        rss = sum(x.memory_info().rss for x in procs) / (1024 * 1024)
        threads = sum(x.num_threads() for x in procs)
        print(f"процессов с main.py: {len(procs)}")
        print(f"CPU: {cpu:.1f}% одного ядра")
        print(f"RAM: {rss:.0f} МБ")
        print(f"потоков: {threads}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
