import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository


class ReportRangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "range.db")
        self.repo = Repository(self.db)
        self.bank = self.repo.add_account("工资卡", "debit", 1_000_000)
        self.food = self.repo.categories("expense")[0].id
        self.salary = self.repo.categories("income")[0].id

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def expense(self, day: str, amount: int, **kwargs) -> int:
        return self.repo.add_transaction(
            date=day,
            kind="expense",
            amount=amount,
            account_id=self.bank,
            category_id=self.food,
            **kwargs,
        )

    def income(self, day: str, amount: int, **kwargs) -> int:
        return self.repo.add_transaction(
            date=day,
            kind="income",
            amount=amount,
            account_id=self.bank,
            category_id=self.salary,
            **kwargs,
        )

    def test_totals_and_trend(self) -> None:
        self.expense("2026-01-05", 10_000)
        self.expense("2026-02-05", 20_000)
        self.income("2026-02-06", 50_000)
        report = self.repo.range_report("2026-01-01", "2026-02-28")
        self.assertEqual(report.income, 50_000)
        self.assertEqual(report.expense, 30_000)
        self.assertEqual(report.net, 20_000)
        self.assertEqual(report.savings_rate, 40.0)
        self.assertEqual(
            [(point.month, point.income, point.expense) for point in report.trend],
            [("2026-01", 0, 10_000), ("2026-02", 50_000, 20_000)],
        )

    def test_previous_period_and_year(self) -> None:
        self.expense("2025-03-05", 500)
        self.income("2025-03-06", 4_000)
        self.expense("2026-02-05", 2_000)
        self.expense("2026-03-05", 1_000)
        self.income("2026-03-06", 5_000)
        report = self.repo.range_report("2026-03-01", "2026-03-31")
        self.assertEqual(report.previous_expense, 2_000)
        self.assertEqual(report.previous_income, 0)
        self.assertEqual(report.year_expense, 500)
        self.assertEqual(report.year_income, 4_000)

    def test_refund_is_netted_from_expense(self) -> None:
        original = self.expense("2026-01-05", 10_000)
        self.income("2026-01-06", 3_000, refund_of_id=original)
        report = self.repo.range_report("2026-01-01", "2026-01-31")
        self.assertEqual(report.income, 0)
        self.assertEqual(report.expense, 7_000)
        self.assertEqual(sum(item.amount for item in report.breakdown), 7_000)

    def test_dimensions(self) -> None:
        txn = self.expense("2026-01-05", 10_000, tags=["必要"])
        self.repo.set_transaction_metadata(
            txn, splits=[(self.food, 10_000, "")]
        )
        by_tag = self.repo.range_report("2026-01-01", "2026-01-31", "tag")
        self.assertEqual([(item.name, item.amount) for item in by_tag.breakdown], [("必要", 10_000)])
        by_account = self.repo.range_report("2026-01-01", "2026-01-31", "account")
        self.assertEqual([(item.name, item.amount) for item in by_account.breakdown], [("工资卡", 10_000)])

    def test_invalid_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "开始日期"):
            self.repo.range_report("2026-02-01", "2026-01-01")


if __name__ == "__main__":
    unittest.main()
