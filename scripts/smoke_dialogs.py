import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from finboard.core.database import Database
from finboard.core.demo import seed_demo
from finboard.core.repository import Repository
from finboard.core.service import FinanceService
from finboard.ui.dialogs import (
    AccountDialog,
    BudgetDialog,
    CategoryDialog,
    TransactionDialog,
)
from finboard.ui.theme import apply_theme


def main() -> None:
    app = QApplication([])
    apply_theme(app, "light")
    path = Path(tempfile.mkdtemp()) / "dialog-test.db"
    db = Database(path)
    repo = Repository(db)
    seed_demo(repo)
    service = FinanceService(repo)

    dialog = TransactionDialog(service)
    assert dialog.account_combo.count() >= 1
    dialog.amount_input.setText("88.50")
    dialog.payee_input.setText("测试商户")
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted

    txn = repo.recent_transactions(1)[0]
    edit = TransactionDialog(service, txn)
    assert edit.amount_input.text() == f"{txn.amount // 100}.{txn.amount % 100:02d}"
    edit._save()
    assert edit.result() == QDialog.DialogCode.Accepted

    transfer = TransactionDialog(service)
    transfer.kind_control.set_value("transfer")
    transfer._kind_changed("transfer")
    transfer.amount_input.setText("10")
    transfer._save()
    assert transfer.result() == QDialog.DialogCode.Accepted

    account = AccountDialog(service)
    account.name_input.setText("测试账户")
    account.opening_input.setText("-1234.56")
    account._save()
    assert account.result() == QDialog.DialogCode.Accepted
    created = next(
        (a for a in repo.accounts(include_archived=True) if a.name == "测试账户"), None
    )
    assert created is not None and created.opening_balance == -123456, created

    category = CategoryDialog(service)
    category.name_input.setText("测试分类")
    category._save()
    assert category.result() == QDialog.DialogCode.Accepted

    line = repo.budget_lines(repo.month_stats().month)[0]
    budget = BudgetDialog(service, line.month, line)
    budget._save()
    assert budget.result() == QDialog.DialogCode.Accepted

    print("dialogs ok", repo.summary_text())
    db.close()


if __name__ == "__main__":
    main()
