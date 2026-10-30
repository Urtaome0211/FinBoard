"""UI tests for 2.1 holdings/savings dialogs."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from finboard.core.database import Database  # noqa: E402
from finboard.core.repository import Repository  # noqa: E402
from finboard.core.service import FinanceService  # noqa: E402
from finboard.i18n import set_language  # noqa: E402
from finboard.ui.dialogs.goal_dialog import GoalDepositDialog, GoalDialog  # noqa: E402
from finboard.ui.dialogs.holdings_dialog import CashDialog, HoldingDialog  # noqa: E402


class V21DialogTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language("zh")
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_goal_dialog_saves_goal(self) -> None:
        dialog = GoalDialog(self.service)
        try:
            dialog.name_input.setText("应急金")
            dialog.target_input.setText("50,000")
            dialog.saved_input.setText("10,000")
            dialog.save_button.click()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            goals = self.repo.savings_goals()
            self.assertEqual(len(goals), 1)
            self.assertEqual(goals[0].name, "应急金")
            self.assertEqual(goals[0].target_amount, 5_000_000)
            self.assertEqual(goals[0].saved_amount, 1_000_000)
        finally:
            dialog.deleteLater()

    def test_goal_deposit_dialog_saves_via_button(self) -> None:
        goal_id = self.repo.add_savings_goal("旅行", 500_000, saved_amount=100_000)
        goal = self.repo.get_savings_goal(goal_id)
        dialog = GoalDepositDialog(self.service, goal)
        try:
            dialog.amount_input.setText("2000")
            dialog.save_button.click()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            self.assertEqual(self.repo.get_savings_goal(goal_id).saved_amount, 300_000)
        finally:
            dialog.deleteLater()

    def test_holding_dialog_saves_holding(self) -> None:
        account_id = self.repo.add_account("证券账户", "investment", 0)
        account = self.repo.get_account(account_id)
        dialog = HoldingDialog(self.service, account)
        try:
            dialog.name_input.setText("沪深300ETF")
            dialog.symbol_input.setText("510300")
            dialog.quantity_input.setText("100")
            dialog.cost_input.setText("4.00")
            dialog.price_input.setText("4.50")
            dialog.save_button.click()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            holdings = self.repo.holdings(account_id)
            self.assertEqual(len(holdings), 1)
            self.assertEqual(holdings[0].quantity_units, 100_000_000)
            self.assertEqual(holdings[0].cost_value, 40_000)
            self.assertEqual(holdings[0].market_value, 45_000)
        finally:
            dialog.deleteLater()

    def test_holding_dialog_rejects_bad_quantity(self) -> None:
        account_id = self.repo.add_account("证券账户2", "investment", 0)
        account = self.repo.get_account(account_id)
        dialog = HoldingDialog(self.service, account)
        try:
            dialog.name_input.setText("测试")
            dialog.quantity_input.setText("0")
            dialog.cost_input.setText("10")
            dialog.price_input.setText("12")
            dialog.save_button.click()
            self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
            self.assertEqual(self.repo.holdings(account_id), [])
        finally:
            dialog.deleteLater()

    def test_cash_dialog_saves_cash(self) -> None:
        account_id = self.repo.add_account("证券账户3", "investment", 100_000)
        self.repo.add_holding(
            account_id,
            "ETF",
            quantity_units=100_000_000,
            cost_price=40_000,
            price=45_000,
        )
        dialog = CashDialog(self.service, self.repo.get_account(account_id))
        try:
            dialog.amount_input.setText("5,000")
            dialog.save_button.click()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            account = self.repo.get_account(account_id)
            self.assertEqual(account.cash_balance, 500_000)
            self.assertEqual(account.balance, 5_000_000)
        finally:
            dialog.deleteLater()



if __name__ == "__main__":
    unittest.main()
