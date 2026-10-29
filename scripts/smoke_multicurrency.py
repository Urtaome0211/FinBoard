"""Render the multi-currency states without network access.

Run with ``PYTHONPATH=. python scripts/smoke_multicurrency.py``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from finboard.core.database import Database  # noqa: E402
from finboard.core.rates import RateSnapshot  # noqa: E402
from finboard.core.repository import Repository  # noqa: E402
from finboard.core.service import FinanceService  # noqa: E402
from finboard.ui.main_window import MainWindow  # noqa: E402
from finboard.ui.theme import apply_theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "multi"
RATES = {"USD": 0.15, "EUR": 0.13, "GBP": 0.11, "JPY": 23.0, "HKD": 1.1}


def main() -> int:
    app = QApplication(sys.argv[:1])
    apply_theme(app, "light")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "multi.db")
        repo = Repository(db)
        repo.rates.save(RateSnapshot(date="2026-10-29", rates=RATES))
        cny = repo.add_account("人民币储蓄卡", "debit", 2_000_000)
        usd = repo.add_account("美元储蓄卡", "debit", 150_000, currency="USD")
        card = repo.add_account("美元信用卡", "credit", 80_000, currency="USD")
        food = repo.find_category("餐饮", "expense").id
        shopping = repo.find_category("购物", "expense").id
        repo.add_transaction(
            date="2026-10-28",
            kind="expense",
            amount=2_500,
            currency="USD",
            account_id=cny,
            category_id=food,
            payee="Airport Cafe",
            note="美元消费，人民币账户入账",
        )
        repo.add_transaction(
            date="2026-10-27",
            kind="expense",
            amount=1_200,
            currency="USD",
            account_id=usd,
            category_id=shopping,
            payee="Amazon",
        )
        repo.add_transaction(
            date="2026-10-26",
            kind="transfer",
            amount=100_000,
            currency="CNY",
            account_id=cny,
            to_account_id=usd,
            note="购汇",
        )
        repo.add_transaction(
            date="2026-10-25",
            kind="income",
            amount=50_000,
            currency="CNY",
            account_id=cny,
            category_id=repo.find_category("工资", "income").id,
            payee="工资",
        )
        service = FinanceService(repo, "CNY")
        window = MainWindow(service)
        window.show()
        for _ in range(3):
            app.processEvents()
        for key in ("dashboard", "accounts", "transactions", "reports", "settings"):
            window.navigate(key)
            for _ in range(3):
                app.processEvents()
            window.grab().save(str(OUT / f"{key}.png"))
            print(key, window.size().width(), window.size().height(), "visible", window.isVisible())
        window.close()
        db.close()
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
