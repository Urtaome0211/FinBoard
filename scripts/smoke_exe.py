"""Launch the packaged exe, capture the desktop, then terminate it."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "FinBoard" / "FinBoard.exe"
DB = ROOT / "build" / "exe-smoke.db"
ENV = os.environ.copy()
# Git Bash exports TEMP=/tmp, which is not a valid Windows path. Emulate
# Explorer/CMD's Windows-style temp directory for the packaged app.
ENV["TEMP"] = ENV["TMP"] = str(Path.home() / "AppData" / "Local" / "Temp")

proc = subprocess.Popen(
    [str(EXE), "--db", str(DB)],
    cwd=ROOT,
    env=ENV,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print("pid", proc.pid, "db", DB)
for _ in range(20):
    time.sleep(0.5)
    if proc.poll() is not None:
        print("exited early", proc.returncode)
        break
else:
    print("running after 10s")
    ImageGrab.grab().save(ROOT / "build" / "exe-smoke.png")
    print("saved build/exe-smoke.png")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
print("db exists", DB.exists())
