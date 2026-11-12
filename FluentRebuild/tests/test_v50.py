"""Tests for the 5.0 core financial model additions."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from finboard_fluent.core import csv_io
from finboard_fluent.core.database import Database
from finboard_fluent.core.dates import add_months
from finboard_fluent.core.models import CsvRule
from finboard_fluent.core.repository import Repository


class CoreModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self._tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.account = self.repo.add_account("储蓄卡", "debit", 100_000)
        self.expense = self.repo.categories("expense")[0]
        self.income = self.repo.categories("income")[0]

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_schema_15_tables(self) -> None:
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 19)
        names = {
            row[0]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {
                "fixed_asset_valuations",
                "debts",
                "planned_transactions",
                "receivables",
            }.issubset(names)
        )

    def test_fixed_asset_valuation_history(self) -> None:
        asset_id = self.repo.add_fixed_asset(
            "相机", "other", 800_000, 900_000, "2026-01-01"
        )
        self.repo.record_fixed_asset_valuation(
            asset_id, 1_200_000, "2026-06-01"
        )
        self.assertEqual(self.repo.fixed_asset_value_at("2026-05-31"), 900_000)
        self.assertEqual(self.repo.fixed_asset_value_at("2026-07-01"), 1_200_000)
        self.assertEqual(self.repo.get_fixed_asset(asset_id).current_value, 1_200_000)
        self.assertEqual(len(self.repo.fixed_asset_valuations(asset_id)), 2)

    def test_account_balance_and_net_worth_history(self) -> None:
        self.repo.add_transaction(
            date="2026-08-15",
            kind="income",
            amount=50_000,
            account_id=self.account,
            category_id=self.income.id,
        )
        self.repo.add_transaction(
            date="2026-09-10",
            kind="expense",
            amount=30_000,
            account_id=self.account,
            category_id=self.expense.id,
        )
        self.assertEqual(self.repo.account_balance_at(self.account, "2026-08-31"), 150_000)
        self.assertEqual(self.repo.account_balance_at(self.account, "2026-09-30"), 120_000)
        history = self.repo.net_worth_history(3, "2026-10")
        self.assertEqual([point.month for point in history], ["2026-08", "2026-09", "2026-10"])
        self.assertEqual([point.net for point in history], [150_000, 120_000, 120_000])

    def test_loan_schedule_credit_cycle_and_payoff(self) -> None:
        loan = self.repo.add_account("房贷", "loan", -1_000_000)
        self.repo.save_debt(
            loan,
            kind="loan",
            principal=1_000_000,
            annual_rate_bp=490,
            term_months=12,
            start_date="2026-01-15",
        )
        schedule = self.repo.debt_schedule(loan)
        self.assertEqual(len(schedule), 12)
        self.assertEqual(schedule[0].payment, 85_562)
        self.assertEqual(schedule[-1].balance, 0)

        card = self.repo.add_account("信用卡", "credit", -50_000)
        self.repo.save_debt(
            card,
            kind="credit",
            annual_rate_bp=1800,
            billing_day=5,
            due_day=20,
            credit_limit=100_000,
        )
        cycle = self.repo.debt_credit_cycle(card)
        self.assertIsNotNone(cycle)
        self.assertGreaterEqual(cycle.days_until_due, 0)

        plan = self.repo.debt_payoff_plan(extra_monthly=10_000)
        self.assertGreater(plan.months, 0)
        self.assertEqual(plan.order[0], "信用卡")

    def test_planned_transaction_and_forecast(self) -> None:
        planned_id = self.repo.add_planned_transaction(
            "2026-12-01",
            "expense",
            50_000,
            self.account,
            category_id=self.expense.id,
            payee="学费",
        )
        forecast = self.repo.cash_flow_forecast(2, "2026-12")
        self.assertEqual(forecast[0].expense, 50_000)
        transaction_id = self.repo.confirm_planned_transaction(planned_id)
        self.assertTrue(transaction_id > 0)
        self.assertEqual(
            self.repo.get_planned_transaction(planned_id).status, "done"
        )
        after = self.repo.cash_flow_forecast(2, "2026-12")
        self.assertEqual(after[0].expense, 0)

    def test_csv_preset_skips_non_cash_flow_rows(self) -> None:
        path = Path(self._tmp.name) / "alipay.csv"
        path.write_text(
            "交易时间,收/支,金额(元),交易对方,商品说明\n"
            "2026-11-01 12:00:00,支出,12.50,便利店,午餐\n"
            "2026-11-02 08:00:00,不计收支,0.00,余额宝,转入\n",
            encoding="utf-8",
        )
        rule = CsvRule(
            id=0,
            name="支付宝",
            mapping={
                "date": "交易时间",
                "kind": "收/支",
                "amount": "金额(元)",
                "payee": "交易对方",
                "note": "商品说明",
            },
        )
        result = csv_io.import_csv(
            self.repo,
            path,
            rule=rule,
            default_account_id=self.account,
        )
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.skipped, 1)
        row = self.repo.recent_transactions(1)[0]
        self.assertEqual(row.date, "2026-11-01")
        self.assertEqual(row.amount, 1_250)
        self.assertEqual(row.payee, "便利店")

    def test_fixed_costs_and_tag_and_daily_breakdown(self) -> None:
        from finboard_fluent.core.insights import detect_fixed_costs
        from finboard_fluent.core.models import Transaction

        today = date.today()
        transactions = []
        for index, months in enumerate((1, 2, 3), start=1):
            day = add_months(today.isoformat(), -months)
            self.repo.add_transaction(
                date=day,
                kind="expense",
                amount=100_000,
                account_id=self.account,
                category_id=self.expense.id,
                payee="房东",
                tags=["居住"],
            )
            transactions.append(
                Transaction(
                    id=index,
                    date=day,
                    kind="expense",
                    amount=100_000,
                    account_id=self.account,
                    account_name="储蓄卡",
                    category_name="居住",
                    payee="房东",
                )
            )
        costs = detect_fixed_costs(transactions)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].payee, "房东")
        self.assertEqual(costs[0].monthly, 100_000)

        self.repo.add_transaction(
            date=today.isoformat(),
            kind="expense",
            amount=5_000,
            account_id=self.account,
            category_id=self.expense.id,
            payee="咖啡店",
            tags=["测试"],
        )
        month = today.strftime("%Y-%m")
        tags = self.repo.tag_breakdown(month)
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0].name, "测试")
        self.assertEqual(tags[0].amount, 5_000)
        daily = self.repo.daily_expense(month)
        self.assertTrue(daily)
        self.assertEqual(sum(daily.values()), 5_000)

    def test_xirr_and_holding_allocation_metadata(self) -> None:
        from datetime import date

        from finboard_fluent.core.investing import xirr

        rate = xirr(
            [(date(2025, 1, 1), -100_000), (date(2026, 1, 1), 110_000)]
        )
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 0.10, places=2)

        account = self.repo.add_account("投资", "investment", 0)
        holding_id = self.repo.add_holding(
            account,
            "沪深300",
            quantity_units=1_000_000,
            cost_price=400,
            price=520,
            asset_class="股票",
            region="中国",
        )
        holding = self.repo.get_holding(holding_id)
        self.assertEqual(holding.asset_class, "股票")
        self.assertEqual(holding.region, "中国")
        self.assertIsNone(self.repo.portfolio_xirr(account))

    def test_receivables_do_not_touch_transactions(self) -> None:
        receivable_id = self.repo.add_receivable(
            direction="receivable",
            counterparty="小王",
            amount=10_000,
            due_date="2026-12-31",
            account_id=self.account,
        )
        self.assertEqual(self.repo.receivables_totals()["receivable"], 10_000)
        before = self.repo.count_transactions()
        self.repo.settle_receivable(receivable_id)
        self.assertEqual(self.repo.count_transactions(), before)
        self.assertEqual(self.repo.receivables_totals()["receivable"], 0)


if __name__ == "__main__":
    unittest.main()
