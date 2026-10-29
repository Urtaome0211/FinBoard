"""Exchange-rate and multi-currency regression tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.csv_io import export_csv, import_csv
from finboard.core.database import Database
from finboard.core.models import TransactionFilter
from finboard.core.rates import RateError, RateSnapshot, RateStore
from finboard.core.repository import Repository


class RateConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "rates.db")
        self.repo = Repository(self.db)
        self.rates = self.repo.rates
        self.rates.save(
            RateSnapshot(
                date="2026-10-29",
                rates={"USD": 0.15, "EUR": 0.13, "GBP": 0.11, "JPY": 23.0, "HKD": 1.1},
            )
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_anchor_and_cross_conversion(self) -> None:
        self.assertEqual(self.rates.convert(10_000, "CNY", "USD", "2026-10-29"), 1_500)
        self.assertEqual(self.rates.convert(1_500, "USD", "CNY", "2026-10-29"), 10_000)
        self.assertEqual(self.rates.convert(1_000, "USD", "EUR", "2026-10-29"), 867)

    def test_falls_back_to_latest_earlier_quote(self) -> None:
        # 2026-10-25 is a Sunday; Friday's quote is used.
        self.assertEqual(self.rates.convert(10_000, "CNY", "USD", "2026-10-25"), 1_500)

    def test_missing_currency_reports_rate_error(self) -> None:
        with self.assertRaises(RateError):
            self.rates.convert(100, "CNY", "CHF", "2026-10-29")

    def test_foreign_expense_and_month_stats(self) -> None:
        usd = self.repo.add_account("美元卡", "debit", 0, currency="USD")
        cny = self.repo.add_account("人民币卡", "debit", 100_000)
        self.repo.add_transaction(
            date="2026-10-29",
            kind="expense",
            amount=1_000,
            currency="USD",
            account_id=cny,
            category_id=self.repo.find_category("餐饮", "expense").id,
        )
        self.assertEqual(self.repo.get_account(usd).balance, 0)
        self.assertEqual(self.repo.get_account(cny).balance, 93_333)
        self.assertEqual(self.repo.month_stats("2026-10").expense, 6_667)

    def test_cross_currency_transfer(self) -> None:
        cny = self.repo.add_account("人民币卡", "debit", 100_000)
        usd = self.repo.add_account("美元卡", "debit", 0, currency="USD")
        txn = self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=10_000,
            currency="CNY",
            account_id=cny,
            to_account_id=usd,
        )
        row = self.repo.get_transaction(txn)
        self.assertEqual(row.to_amount, 1_500)
        self.assertEqual(row.to_account_currency, "USD")
        self.assertEqual(self.repo.get_account(cny).balance, 90_000)
        self.assertEqual(self.repo.get_account(usd).balance, 1_500)
        self.assertEqual(self.repo.net_worth().assets, 100_000)

    def test_positive_liability_stays_a_liability(self) -> None:
        self.repo.add_account("信用卡", "credit", 200_000)
        worth = self.repo.net_worth()
        self.assertEqual(worth.assets, 0)
        self.assertEqual(worth.liabilities, 200_000)

    def test_csv_keeps_transaction_currency(self) -> None:
        usd = self.repo.add_account("美元卡", "debit", 0, currency="USD")
        self.repo.add_transaction(
            date="2026-10-29",
            kind="expense",
            amount=1_234,
            currency="USD",
            account_id=usd,
            category_id=self.repo.find_category("餐饮", "expense").id,
            payee="Coffee",
        )
        path = Path(self.tmp.name) / "currency.csv"
        export_csv(self.repo, path)
        self.assertIn("币种", path.read_text(encoding="utf-8-sig").splitlines()[0])

        other = Database(Path(self.tmp.name) / "other.db")
        other_repo = Repository(other)
        try:
            other_repo.add_account("美元卡", "debit", 0, currency="USD")
            result = import_csv(other_repo, path)
            self.assertEqual(result.imported, 1)
            rows = other_repo.transactions(TransactionFilter())
            self.assertEqual(rows[0].currency, "USD")
            self.assertEqual(rows[0].amount, 1_234)
            self.assertEqual(rows[0].account_amount, 1_234)
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
