"""Render every dialog so layout regressions are visible before packaging."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from finboard.core.database import Database
from finboard.core.demo import seed_demo
from finboard.core.repository import Repository
from finboard.core.service import FinanceService
from finboard.ui.dialogs import (
    AccountDialog,
    BudgetDialog,
    CategoryDialog,
    CategoryManagerDialog,
    TransactionDialog,
)
from finboard.ui.theme import apply_theme


def main() -> None:
    app = QApplication([])
    app.setStyle("Fusion")
    apply_theme(app, "light")
    tmp = Path(tempfile.mkdtemp(prefix="finboard-dialogs-"))
    db = Database(tmp / "demo.db")
    repo = Repository(db)
    seed_demo(repo)
    service = FinanceService(repo)

    out = Path("build") / "dialogs"
    out.mkdir(parents=True, exist_ok=True)
    dialogs = {
        "transaction": TransactionDialog(service),
        "account": AccountDialog(service),
        "category": CategoryDialog(service),
        "budget": BudgetDialog(service, "2026-10"),
        "categories": CategoryManagerDialog(service),
    }
    for key, dialog in dialogs.items():
        dialog.show()
        app.processEvents()
        app.processEvents()
        dialog.grab().save(str(out / f"{key}.png"))
        print(f"{key}: {dialog.width()}x{dialog.height()}")
        dialog.close()
    db.close()


if __name__ == "__main__":
    main()
