"""Tests for 2.1 holdings, budget rollover, savings goals and forecasts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class V21CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_v7_tables_exist(self) -> None:
        names = {
            row[0]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {"holdings", "savings_goals", "recurring_transactions"} <= names
        )
        columns = {
            row[1]
            for row in self.db.conn.execute("PRAGMA table_info(budgets)")
        }
        self.assertIn("rollover", columns)

    def test_budget_rollover_carries_only_positive_remaining(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 1_000_000)
        dining = self.repo.find_category("餐饮", "expense")
        self.repo.upsert_budget("2026-10", 0, 100_000, rollover=True)
        self.repo.upsert_budget("2026-11", 0, 100_000, rollover=False)
        self.repo.add_transaction(
            date="2026-10-12",
            kind="expense",
            amount=30_000,
            account_id=cash,
            category_id=dining.id,
        )
        october = {line.category_id: line for line in self.repo.budget_lines("2026-10")}
        november = {line.category_id: line for line in self.repo.budget_lines("2026-11")}
        self.assertEqual(october[0].available, 100_000)
        self.assertEqual(november[0].rollover, 70_000)
        self.assertEqual(november[0].available, 170_000)
        self.assertEqual(november[0].remaining, 170_000)

    def test_budget_rollover_does_not_carry_overspend(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 1_000_000)
        dining = self.repo.find_category("餐饮", "expense")
        self.repo.upsert_budget("2026-10", 0, 100_000, rollover=True)
        self.repo.upsert_budget("2026-11", 0, 100_000)
        self.repo.add_transaction(
            date="2026-10-12",
            kind="expense",
            amount=150_000,
            account_id=cash,
            category_id=dining.id,
        )
        november = next(line for line in self.repo.budget_lines("2026-11") if line.is_overall)
        self.assertEqual(november.rollover, 0)

    def test_holding_values_and_summary(self) -> None:
        account = self.repo.add_account("证券账户", "investment", 0)
        self.repo.add_holding(
            account,
            "沪深300ETF",
            symbol="510300",
            quantity_units=100_000_000,
            cost_price=10_000,
            price=12_000,
        )
        holdings = self.repo.holdings(account)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].cost_value, 1_000_000)
        self.assertEqual(holdings[0].market_value, 1_200_000)
        self.assertEqual(holdings[0].profit, 200_000)
        self.assertEqual(holdings[0].return_rate, 20.0)
        summary = self.repo.holdings_summary(account)
        self.assertEqual((summary.cost, summary.market), (1_000_000, 1_200_000))

    def test_holdings_only_for_investment_accounts(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 0)
        with self.assertRaisesRegex(ValueError, "投资"):
            self.repo.add_holding(
                cash,
                "测试",
                quantity_units=1_000_000,
                cost_price=100,
                price=100,
            )

    def test_sync_holdings_value_creates_valuation(self) -> None:
        account = self.repo.add_account("证券账户", "investment", 0)
        self.repo.add_holding(
            account,
            "ETF",
            quantity_units=100_000_000,
            cost_price=10_000,
            price=12_000,
        )
        self.service.sync_holdings_value(account)
        self.assertEqual(self.repo.get_account(account).balance, 1_200_000)
        self.assertEqual(len(self.repo.valuations(account)), 1)

    def test_investment_cash_and_holdings_make_total(self) -> None:
        account = self.repo.add_account("证券账户", "investment", 100_000)
        self.repo.add_holding(
            account,
            "ETF",
            quantity_units=100_000_000,
            cost_price=40_000,
            price=45_000,
        )
        current = self.repo.get_account(account)
        self.assertEqual(current.holdings_value, 4_500_000)
        self.assertEqual(current.cash_balance, 100_000)
        self.assertEqual(current.balance, 4_600_000)
        self.service.set_cash_balance(account, 500_000)
        current = self.repo.get_account(account)
        self.assertEqual(current.cash_balance, 500_000)
        self.assertEqual(current.balance, 5_000_000)
        total = self.service.sync_holdings_value(account, "2026-10-30")
        self.assertEqual(total, 5_000_000)
        valuation = self.repo.valuations(account)[0]
        self.assertEqual(valuation.value, 4_600_000)
        self.assertEqual(self.repo.get_account(account).balance, 5_000_000)

    def test_investment_cash_rejects_negative(self) -> None:
        account = self.repo.add_account("证券账户", "investment", 0)
        with self.assertRaises(ValueError):
            self.service.set_cash_balance(account, -1)

    def test_savings_goal_progress_and_deposit(self) -> None:
        goal_id = self.repo.add_savings_goal(
            "应急金", target_amount=500_000, saved_amount=100_000
        )
        goal = self.repo.get_savings_goal(goal_id)
        self.assertEqual(goal.remaining, 400_000)
        self.assertEqual(goal.progress, 20.0)
        self.assertFalse(goal.completed)
        self.service.add_goal_funds(goal_id, 400_000)
        self.assertTrue(self.repo.get_savings_goal(goal_id).completed)
        self.repo.add_goal_funds(goal_id, -10_000_000)
        self.assertEqual(self.repo.get_savings_goal(goal_id).saved_amount, 0)

    def test_forecast_projects_recurring_expense(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 1_000_000)
        dining = self.repo.find_category("餐饮", "expense")
        self.repo.add_recurring(
            name="房租",
            kind="expense",
            amount=100_000,
            account_id=cash,
            category_id=dining.id,
            frequency="monthly",
            start_date="2026-11-01",
        )
        points = self.repo.cash_flow_forecast(months=2, start_month="2026-11")
        self.assertEqual(points[0].month, "2026-11")
        self.assertEqual(points[0].expense, 100_000)
        self.assertEqual(points[0].ending_cash, 900_000)
        self.assertEqual(points[1].ending_cash, 800_000)

    def test_forecast_respects_end_date_and_ignores_transfers(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 1_000_000)
        bank = self.repo.add_account("测试卡", "debit", 0)
        dining = self.repo.find_category("餐饮", "expense")
        self.repo.add_recurring(
            name="订阅",
            kind="expense",
            amount=10_000,
            account_id=cash,
            category_id=dining.id,
            frequency="monthly",
            start_date="2026-11-01",
            end_date="2026-11-30",
        )
        self.repo.add_recurring(
            name="内部转账",
            kind="transfer",
            amount=50_000,
            account_id=cash,
            to_account_id=bank,
            frequency="monthly",
            start_date="2026-11-01",
        )
        points = self.repo.cash_flow_forecast(months=3, start_month="2026-11")
        self.assertEqual([point.expense for point in points], [10_000, 0, 0])
        self.assertEqual(points[-1].ending_cash, 990_000)

    def test_forecast_starts_with_cash_and_debit_only(self) -> None:
        cash = self.repo.add_account("测试现金", "cash", 100_000)
        self.repo.add_account("测试投资", "investment", 999_999)
        self.repo.add_account("测试信用卡", "credit", -50_000)
        points = self.repo.cash_flow_forecast(months=1, start_month="2026-11")
        self.assertEqual(points[0].ending_cash, 100_000)


if __name__ == "__main__":
    unittest.main()
