"""Render English UI screenshots without touching the real settings.

Run with ``PYTHONPATH=. python scripts/smoke_i18n.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from finboard.core.database import Database  # noqa: E402
from finboard.core.demo import seed_demo  # noqa: E402
from finboard.core.repository import Repository  # noqa: E402
from finboard.core.service import FinanceService  # noqa: E402
from finboard.i18n import set_language  # noqa: E402
from finboard.ui.dialogs import (  # noqa: E402
    AccountDialog,
    BudgetDialog,
    CategoryManagerDialog,
    GoalDialog,
    HoldingDialog,
    HoldingsDialog,
    ReconcileDialog,
    RecurringDialog,
    TransactionDialog,
    ValuationDialog,
)
from finboard.ui.localize import apply_locale, install_localizer, localize_widgets  # noqa: E402
from finboard.ui.main_window import MainWindow  # noqa: E402
from finboard.ui.theme import apply_theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "i18n"


def main() -> int:
    app = QApplication(sys.argv[:1])
    install_localizer(app)
    apply_theme(app, "light")
    OUT.mkdir(parents=True, exist_ok=True)

    # A private settings scope: never change the user's preferred language.
    settings = QSettings("FinBoard-I18N-Smoke", "FinBoard-I18N-Smoke")
    settings.setValue("language", "en")
    set_language("en")
    apply_locale()

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "demo.db")
        repo = Repository(db)
        seed_demo(repo)
        bank = next(a for a in repo.accounts() if a.type == "debit")
        housing = repo.find_category("居住", "expense")
        salary = repo.find_category("工资", "income")
        fund = next(a for a in repo.accounts() if a.type == "investment")
        repo.add_recurring(name="Rent", kind="expense", amount=420_000, account_id=bank.id, category_id=housing.id, frequency="monthly", start_date="2026-10-01", payee="Landlord")
        repo.add_recurring(name="Salary", kind="income", amount=1_850_000, account_id=bank.id, category_id=salary.id, frequency="monthly", start_date="2026-11-05")
        repo.add_recurring(name="Index fund", kind="transfer", amount=100_000, account_id=bank.id, to_account_id=fund.id, frequency="weekly", start_date="2026-10-28")
        repo.add_savings_goal("Emergency fund", target_amount=5_000_000, saved_amount=1_500_000, target_date="2027-06-30")
        repo.add_holding(fund.id, "CSI 300 ETF", symbol="510300", quantity_units=100_000_000, cost_price=40_000, price=45_000)
        investment = repo.find_category("购物", "expense")
        account = next(
            (a for a in repo.accounts() if a.type == "investment"),
            None,
        )

        service = FinanceService(repo, "CNY")
        window = MainWindow(service, settings)
        window.resize(1440, 900)
        window.show()
        for _ in range(3):
            app.processEvents()

        for key in (
            "dashboard",
            "transactions",
            "accounts",
            "budgets",
            "savings",
            "forecast",
            "recurring",
            "reports",
            "settings",
        ):
            window.navigate(key)
            for _ in range(3):
                app.processEvents()
            window.grab().save(str(OUT / f"{key}.png"))
            print(key, window.size().width(), window.size().height())

        legacy = repo.find_category("餐饮", "expense")
        demo_account_id = repo.add_account("示例投资", "investment", 10_000_000)
        repo.set_valuation(demo_account_id, "2026-09-30", 14_000_000, "September close")
        repo.set_valuation(demo_account_id, "2026-10-29", 15_000_000, "October close")
        demo_account = repo.get_account(demo_account_id)
        dialogs = [
            ("transaction", TransactionDialog(service, parent=window)),
            ("account", AccountDialog(service, account, parent=window)),
            ("budget", BudgetDialog(service, "2026-10", parent=window)),
            ("categories", CategoryManagerDialog(service, window)),
            ("recurring", RecurringDialog(service, parent=window)),
            ("holdings", HoldingsDialog(service, fund, parent=window)),
            ("holding", HoldingDialog(service, fund, parent=window)),
            ("goal", GoalDialog(service, parent=window)),
            ("reconcile", ReconcileDialog(service, bank, parent=window)),
        ]
        dialogs.append(("valuation", ValuationDialog(service, demo_account, parent=window)))
        for name, dialog in dialogs:
            dialog.show()
            localize_widgets(dialog)
            for _ in range(2):
                app.processEvents()
            dialog.grab().save(str(OUT / f"dialog-{name}.png"))
            print("dialog", name, dialog.size().width(), dialog.size().height())
            dialog.close()

        # Keep the demo category lookup exercised for future screenshots.
        assert legacy is not None
        window.close()
        db.close()

    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
