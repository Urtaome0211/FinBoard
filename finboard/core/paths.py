"""Filesystem locations for the database, logs and exports."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "FinBoard"


def data_dir() -> Path:
    """Per-user writable directory for the database and logs."""
    override = os.environ.get("FINBOARD_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        path = Path(base) / APP_DIR_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = Path(base) / APP_DIR_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return portable_data_dir()
    return path


def default_db_path() -> Path:
    override = os.environ.get("FINBOARD_DB")
    if override:
        return Path(override).expanduser()
    return data_dir() / "finboard.db"


def demo_db_path() -> Path:
    return data_dir() / "finboard-demo.db"


def log_path() -> Path:
    return data_dir() / "finboard.log"


def attachments_dir() -> Path:
    path = data_dir() / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachment_path(stored_name: str) -> Path:
    name = Path(str(stored_name)).name
    return attachments_dir() / name


def portable_data_dir() -> Path:
    """Writable fallback beside the app when the user profile is unavailable."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path.cwd()
    path = base / "FinBoard-Data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(*parts: str) -> Path:
    """Resolve bundled resources both from source and from a PyInstaller build."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        base = Path(bundle_root) / "finboard" / "resources"
    else:
        base = Path(__file__).resolve().parent.parent / "resources"
    return base.joinpath(*parts)
