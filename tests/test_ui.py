"""UI regression tests that do not need a visible window."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from finboard.core.database import Database  # noqa: E402
from finboard.core.dates import today  # noqa: E402
from finboard.core.rates import RateSnapshot, RateStore  # noqa: E402
from finboard.core.repository import Repository  # noqa: E402
from finboard.core.service import FinanceService  # noqa: E402
from finboard.ui.dialogs.account_dialog import AccountDialog  # noqa: E402
from finboard.ui.dialogs.transaction_dialog import TransactionDialog  # noqa: E402
from finboard.ui.dialogs.valuation_dialog import ValuationDialog  # noqa: E402
from finboard.ui.main_window import MainWindow  # noqa: E402


class AccountDialogTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_editing_account_saves_all_fields(self) -> None:
        account = self.repo.accounts()[0]
        dialog = AccountDialog(self.service, account)
        try:
            dialog.name_input.setText("招商银行储蓄卡")
            dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("debit"))
            dialog.opening_input.setText("1,234.56")
            dialog.note_input.setText("工资卡")
            dialog._save()

            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            updated = self.repo.get_account(account.id)
            self.assertEqual(updated.name, "招商银行储蓄卡")
            self.assertEqual(updated.type, "debit")
            self.assertEqual(updated.opening_balance, 123_456)
            self.assertEqual(updated.note, "工资卡")
        finally:
            dialog.deleteLater()

    def test_new_liability_is_recorded_as_negative_debt(self) -> None:
        dialog = AccountDialog(self.service)
        try:
            dialog.name_input.setText("测试信用卡")
            dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("credit"))
            self.assertEqual(dialog.opening_label.text(), "欠款金额")
            dialog.opening_input.setText("1,234.56")
            dialog._save()

            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            account = next(
                item for item in self.repo.accounts() if item.name == "测试信用卡"
            )
            self.assertEqual(account.opening_balance, -123_456)
            self.assertEqual(account.balance, -123_456)
            self.assertEqual(self.repo.net_worth().liabilities, 123_456)
        finally:
            dialog.deleteLater()

    def test_editing_positive_liability_converts_it_to_debt(self) -> None:
        account_id = self.repo.add_account("旧信用卡", "credit", 128_200)
        account = self.repo.get_account(account_id)
        dialog = AccountDialog(self.service, account)
        try:
            self.assertEqual(dialog.opening_input.text(), "1282.00")
            self.assertIn("直接保存", dialog.hint.text())
            dialog._save()
            updated = self.repo.get_account(account.id)
            self.assertEqual(updated.opening_balance, -128_200)
            self.assertEqual(updated.balance, -128_200)
        finally:
            dialog.deleteLater()

    def test_new_foreign_account_saves_currency(self) -> None:
        self.repo.rates.save(
            RateSnapshot(date="2026-10-29", rates={"USD": 0.15, "EUR": 0.13})
        )
        dialog = AccountDialog(self.service)
        try:
            dialog.name_input.setText("美元账户")
            dialog.currency_combo.setCurrentIndex(dialog.currency_combo.findData("USD"))
            dialog.opening_input.setText("100.00")
            dialog._save()
            account = next(
                item for item in self.repo.accounts() if item.name == "美元账户"
            )
            self.assertEqual(account.currency, "USD")
            self.assertEqual(account.opening_balance, 10_000)
        finally:
            dialog.deleteLater()

    def test_currency_is_locked_after_account_has_transactions(self) -> None:
        account_id = self.repo.add_account("美元卡", "debit", 0, currency="USD")
        self.repo.add_transaction(
            date="2026-10-29",
            kind="expense",
            amount=100,
            currency="USD",
            account_id=account_id,
            category_id=self.repo.find_category("餐饮", "expense").id,
        )
        dialog = AccountDialog(self.service, self.repo.get_account(account_id))
        try:
            self.assertFalse(dialog.currency_combo.isEnabled())
        finally:
            dialog.deleteLater()


class TransactionDialogTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_wallet_transfer_dialog_saves_calculated_fee(self) -> None:
        alipay = self.repo.add_account("支付宝钱包", "cash", 500_000)
        bank = self.repo.add_account("银行储蓄卡", "debit", 0)
        dialog = TransactionDialog(self.service)
        try:
            dialog.kind_control.set_value("transfer", emit=True)
            dialog.account_combo.setCurrentIndex(
                dialog.account_combo.findData(alipay)
            )
            dialog.amount_input.setText("100.00")
            dialog.to_combo.setCurrentIndex(dialog.to_combo.findData(bank))
            self.assertIn("¥0.10", dialog.fee_value.text())
            dialog._save()

            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            transaction = self.repo.transactions()[0]
            self.assertEqual(transaction.kind, "transfer")
            self.assertEqual(transaction.fee, 10)
            self.assertEqual(self.repo.account_balance(alipay), 489_990)
            self.assertEqual(self.repo.account_balance(bank), 10_000)
        finally:
            dialog.deleteLater()


class ValuationDialogTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_dialog_saves_snapshot_without_closing(self) -> None:
        account_id = self.repo.add_account("证券账户", "investment", 100_000)
        dialog = ValuationDialog(self.service, self.repo.get_account(account_id))
        try:
            dialog.amount_input.setText("1,234.56")
            dialog.note_input.setText("收盘")
            dialog._save()
            account = self.repo.get_account(account_id)
            self.assertEqual(account.last_valuation, 123_456)
            self.assertEqual(account.balance, 123_456)
            self.assertEqual(dialog.latest_value.text(), "¥1,234.56")
        finally:
            dialog.deleteLater()

    def test_account_dialog_locks_valuation_fields(self) -> None:
        account_id = self.repo.add_account("证券账户", "investment", 100_000)
        self.repo.set_valuation(account_id, today(), 200_000)
        dialog = AccountDialog(self.service, self.repo.get_account(account_id))
        try:
            self.assertFalse(dialog.opening_input.isEnabled())
            self.assertFalse(dialog.type_combo.isEnabled())
            self.assertFalse(dialog.currency_combo.isEnabled())
            self.assertIn("最新市值", dialog.hint.text())
        finally:
            dialog.deleteLater()


class RateStartupTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_daily_rate_refresh_runs_in_background(self) -> None:
        original = RateStore.fetch_latest
        RateStore.fetch_latest = staticmethod(
            lambda timeout=9.0: RateSnapshot(
                date="2026-10-29", rates={"USD": 0.15, "EUR": 0.13}
            )
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db = Database(Path(tmp) / "startup.db")
                repo = Repository(db)
                service = FinanceService(repo)
                window = MainWindow(service)
                window.show()
                loop = QEventLoop()
                QTimer.singleShot(2_000, loop.quit)
                loop.exec()
                window.close()
                self.assertTrue(service.rate_store.has_rates())
                self.assertEqual(service.rate_store.latest_date(), "2026-10-29")
                db.close()
        finally:
            RateStore.fetch_latest = original
