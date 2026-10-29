"""Launch the real application bootstrap and close it automatically."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from finboard.app import main as app_main
from finboard.ui.main_window import MainWindow


def main() -> int:
    original_show = MainWindow.show

    def show_then_quit(window: MainWindow) -> None:
        original_show(window)
        QTimer.singleShot(1200, QApplication.instance().quit)

    MainWindow.show = show_then_quit
    path = Path(tempfile.mkdtemp(prefix="finboard-app-")) / "app.db"
    code = app_main(["--db", str(path)])
    print("exit", code, "db", path.exists())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
