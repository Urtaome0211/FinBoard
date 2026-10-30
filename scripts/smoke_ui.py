"""Instantiate every page against a demo database and save a preview."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from finboard.core.database import Database
from finboard.core.demo import seed_demo
from finboard.core.repository import Repository
from finboard.core.service import FinanceService
from finboard.ui.main_window import MainWindow
from finboard.ui.theme import apply_theme


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    apply_theme(app, args.theme)
    tmp = Path(tempfile.mkdtemp(prefix="finboard-ui-"))
    db = Database(tmp / "demo.db")
    repo = Repository(db)
    seed_demo(repo)
    service = FinanceService(repo)
    settings = QSettings("FinBoardTest", "FinBoardTest")
    window = MainWindow(service, settings)
    window.set_theme(args.theme)
    window.resize(1440, 900)
    window.show()
    app.processEvents()
    suffix = "" if args.theme == "light" else "-dark"
    out_dir = Path("build") / f"pages{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in ("dashboard", "transactions", "accounts", "budgets", "recurring", "reports", "settings"):
        window.navigate(key)
        app.processEvents()
        app.processEvents()
        page = window.pages[key]
        if page.scroll_area is not None:
            page.scroll_area.verticalScrollBar().setValue(0)
        window.grab().save(str(out_dir / f"{key}.png"))
        print(f"{key}: {page.width()}x{page.height()} visible={page.isVisible()}")
    window.navigate("dashboard")
    app.processEvents()
    app.processEvents()
    out = Path("build") / f"ui-smoke{suffix}.png"
    out.parent.mkdir(exist_ok=True)
    window.grab().save(str(out))
    print("saved", out, "and", out_dir)
    print("saved", out)
    window.close()
    db.close()


if __name__ == "__main__":
    main()
