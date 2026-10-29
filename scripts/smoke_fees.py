"""Render the wallet-fee states without touching the user's database."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from finboard.core.database import Database
from finboard.core.repository import Repository
from finboard.core.service import FinanceService
from finboard.ui.dialogs.transaction_dialog import TransactionDialog
from finboard.ui.main_window import MainWindow
from finboard.ui.theme import apply_theme

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "fees"


def main() -> int:
    app = QApplication(sys.argv[:1])
    apply_theme(app, "light")
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "fees.db")
        repo = Repository(db)
        alipay = repo.add_account("支付宝钱包", "cash", 500_000)
        wechat = repo.add_account("微信钱包", "cash", 100_000)
        bank = repo.add_account("银行储蓄卡", "debit", 0)
        repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=100_000,
            account_id=alipay,
            to_account_id=bank,
            note="提现到银行卡",
        )
        repo.add_transaction(
            date="2026-10-28",
            kind="transfer",
            amount=100,
            account_id=wechat,
            to_account_id=bank,
            note="微信零钱提现",
        )
        service = FinanceService(repo, "CNY")
        window = MainWindow(service)
        window.show()
        for _ in range(4):
            app.processEvents()
        for key in ("dashboard", "accounts", "transactions", "reports"):
            window.navigate(key)
            for _ in range(3):
                app.processEvents()
            window.grab().save(str(OUT / f"{key}.png"))

        window.navigate("transactions")
        app.processEvents()
        dialog = TransactionDialog(service)
        dialog.kind_control.set_value("transfer", emit=True)
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData(alipay))
        dialog.amount_input.setText("1000.00")
        dialog.to_combo.setCurrentIndex(dialog.to_combo.findData(bank))
        for _ in range(3):
            app.processEvents()
        dialog.show()
        for _ in range(4):
            app.processEvents()
        dialog.grab().save(str(OUT / "dialog-transfer-fee.png"))
        dialog.close()
        window.close()
        db.close()
    print("saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
