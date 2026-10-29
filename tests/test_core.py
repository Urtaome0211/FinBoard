"""Core regression tests: money, dates, SQLite repository, CSV and demo data."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.csv_io import export_csv, import_csv
from finboard.core.database import Database
from finboard.core.dates import month_choices, month_of, today
from finboard.core.demo import seed_demo
from finboard.core.models import TransactionFilter
from finboard.core.money import (
    format_cents,
    parse_amount,
    parse_signed_amount,
    percentage,
)
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class MoneyTests(unittest.TestCase):
    def test_parse_amount_accepts_common_input(self) -> None:
        self.assertEqual(parse_amount("1,234.56"), 123_456)
        self.assertEqual(parse_amount("¥ 0.01"), 1)
        self.assertEqual(parse_amount("１２.３０"), 1_230)

    def test_parse_amount_rejects_non_positive(self) -> None:
        for value in ("0", "-1", "", "abc"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_amount(value)

    def test_signed_amount_allows_negative(self) -> None:
        self.assertEqual(parse_signed_amount("-12.34"), -1_234)
        self.assertEqual(parse_signed_amount("0"), 0)

    def test_format_cents(self) -> None:
        self.assertEqual(format_cents(123_456), "¥1,234.56")
        self.assertEqual(format_cents(-123_456), "-¥1,234.56")
        self.assertEqual(format_cents(123_456, plus=True), "+¥1,234.56")
        self.assertEqual(format_cents(0), "¥0.00")

    def test_percentage_handles_zero_total(self) -> None:
        self.assertEqual(percentage(10, 0), 0.0)
        self.assertEqual(percentage(1, 3), 33.3)


class DateTests(unittest.TestCase):
    def test_month_choices_are_recent_and_descending(self) -> None:
        months = month_choices(6)
        self.assertEqual(len(months), 6)
        self.assertEqual(months[0], month_of(today()))
        self.assertGreater(months[0], months[-1])

    def test_month_choices_do_not_include_future(self) -> None:
        for month in month_choices(18):
            self.assertLessEqual(month, month_of(today()))


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_accounts_and_net_worth(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 1_000_000)
        card = self.repo.add_account("信用卡", "credit", -200_000)
        self.repo.add_transaction(
            date="2026-10-01",
            kind="expense",
            amount=10_000,
            account_id=bank,
            category_id=self.repo.find_category("餐饮", "expense").id,
        )
        self.repo.add_transaction(
            date="2026-10-02",
            kind="income",
            amount=50_000,
            account_id=bank,
            category_id=self.repo.find_category("工资", "income").id,
        )
        self.assertEqual(self.repo.account_balance(bank), 1_040_000)
        self.assertEqual(self.repo.account_balance(card), -200_000)
        worth = self.repo.net_worth()
        self.assertEqual(worth.assets, 1_040_000)
        self.assertEqual(worth.liabilities, 200_000)
        self.assertEqual(worth.net, 840_000)
        self.assertAlmostEqual(worth.liability_ratio, 16.1, places=1)

    def test_transfer_moves_both_balances(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 100_000)
        cash_account = next(a for a in self.repo.accounts() if a.name == "现金")
        self.repo.add_transaction(
            date="2026-10-03",
            kind="transfer",
            amount=25_000,
            account_id=bank,
            to_account_id=cash_account.id,
        )
        self.assertEqual(self.repo.account_balance(bank), 75_000)
        self.assertEqual(self.repo.account_balance(cash_account.id), 25_000)

    def test_filter_search_and_month(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 100_000)
        food = self.repo.find_category("餐饮", "expense").id
        self.repo.add_transaction(
            date="2026-09-30",
            kind="expense",
            amount=1_000,
            account_id=bank,
            category_id=food,
            payee="旧咖啡",
        )
        self.repo.add_transaction(
            date="2026-10-01",
            kind="expense",
            amount=2_000,
            account_id=bank,
            category_id=food,
            payee="新咖啡",
        )
        rows = self.repo.transactions(TransactionFilter(month="2026-10"))
        self.assertEqual([row.payee for row in rows], ["新咖啡"])
        rows = self.repo.transactions(TransactionFilter(search="旧"))
        self.assertEqual([row.payee for row in rows], ["旧咖啡"])

    def test_delete_category_moves_rows_to_fallback(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 100_000)
        category = self.repo.add_category("宠物", "expense", "#F2994A")
        txn = self.repo.add_transaction(
            date="2026-10-04",
            kind="expense",
            amount=3_000,
            account_id=bank,
            category_id=category,
        )
        fallback = self.repo.delete_category(category)
        self.assertEqual(fallback, "其他")
        self.assertEqual(self.repo.get_transaction(txn).category_name, "其他")

    def test_budgets_track_spending_and_overall_line(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 100_000)
        food = self.repo.find_category("餐饮", "expense").id
        self.repo.upsert_budget("2026-10", 0, 100_000)
        self.repo.upsert_budget("2026-10", food, 20_000)
        self.repo.add_transaction(
            date="2026-10-05",
            kind="expense",
            amount=25_000,
            account_id=bank,
            category_id=food,
        )
        lines = self.repo.budget_lines("2026-10")
        overall = lines[0]
        food_line = next(line for line in lines if line.category_id == food)
        self.assertTrue(overall.is_overall)
        self.assertEqual(overall.spent, 25_000)
        self.assertEqual(food_line.ratio, 1.25)
        self.assertEqual(food_line.remaining, -5_000)

    def test_csv_round_trip(self) -> None:
        bank = self.repo.add_account("工资卡", "debit", 100_000)
        food = self.repo.find_category("餐饮", "expense").id
        self.repo.add_transaction(
            date="2026-10-06",
            kind="expense",
            amount=4_500,
            account_id=bank,
            category_id=food,
            payee="面馆",
            note="午餐",
        )
        path = Path(self.tmp.name) / "export.csv"
        self.assertEqual(export_csv(self.repo, path), 1)

        other = Database(Path(self.tmp.name) / "import.db")
        other_repo = Repository(other)
        try:
            other_repo.add_account("工资卡", "debit", 0)
            result = import_csv(other_repo, path)
            self.assertEqual(result.imported, 1)
            self.assertEqual(result.skipped, 0)
            self.assertEqual(other_repo.count_transactions(TransactionFilter()), 1)
            self.assertEqual(other_repo.transactions(TransactionFilter())[0].payee, "面馆")
        finally:
            other.close()

    def test_demo_data_has_twelve_month_trend(self) -> None:
        seed_demo(self.repo)
        self.assertGreater(self.repo.count_transactions(TransactionFilter()), 100)
        self.assertGreater(self.repo.net_worth().assets, 0)
        self.assertGreater(self.repo.net_worth().liabilities, 0)
        self.assertEqual(len(self.repo.trend(12)), 12)


class ServiceTests(unittest.TestCase):
    def test_changed_signal_is_emitted_once_per_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "service.db")
            repo = Repository(db)
            service = FinanceService(repo)
            calls: list[int] = []
            service.changed.connect(lambda: calls.append(1))
            account_id = service.add_account("测试卡", "debit", 10_000)
            category = repo.find_category("餐饮", "expense")
            service.add_transaction(
                date="2026-10-07",
                kind="expense",
                amount=1_000,
                account_id=account_id,
                category_id=category.id,
            )
            self.assertEqual(len(calls), 2)
            db.close()


if __name__ == "__main__":
    unittest.main()
