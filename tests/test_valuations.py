"""Investment account daily valuation tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.dates import today
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class ValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.account = self.repo.add_account(
            "证券账户", "investment", 100_000, currency="CNY"
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _balance(self) -> int:
        return self.repo.get_account(self.account).balance

    def _income(self, day: str, amount: int) -> None:
        self.repo.add_transaction(
            date=day,
            kind="income",
            amount=amount,
            account_id=self.account,
            category_id=self.repo.find_category("其他", "income").id,
        )

    def _expense(self, day: str, amount: int) -> None:
        self.repo.add_transaction(
            date=day,
            kind="expense",
            amount=amount,
            account_id=self.account,
            category_id=self.repo.find_category("其他", "expense").id,
        )

    def test_valuation_replaces_opening_and_ignores_flows_on_or_before_date(self) -> None:
        self._expense("2026-01-10", 10_000)
        self._expense("2026-01-31", 3_000)  # 已包含在收盘市值里
        self._income("2026-02-10", 5_000)
        self.repo.set_valuation(self.account, "2026-01-31", 200_000, "一月收盘")
        self.assertEqual(self._balance(), 205_000)
        account = self.repo.get_account(self.account)
        self.assertEqual(account.last_valuation, 200_000)
        self.assertEqual(account.last_valuation_date, "2026-01-31")
        self.assertEqual(account.valuation_count, 1)

    def test_same_day_overwrites_value(self) -> None:
        self.repo.set_valuation(self.account, "2026-02-01", 150_000)
        self.repo.set_valuation(self.account, "2026-02-01", 160_000)
        self.assertEqual(self._balance(), 160_000)
        self.assertEqual(len(self.repo.valuations(self.account)), 1)

    def test_delete_valuation_returns_to_transaction_balance(self) -> None:
        self._expense("2026-01-10", 10_000)
        valuation_id = self.repo.set_valuation(self.account, "2026-02-01", 200_000)
        self.assertEqual(self._balance(), 200_000)
        self.repo.delete_valuation(valuation_id)
        self.assertEqual(self._balance(), 90_000)

    def test_valuation_sorted_desc_and_valuation_at(self) -> None:
        self.repo.set_valuation(self.account, "2026-01-31", 110_000)
        self.repo.set_valuation(self.account, "2026-02-28", 120_000)
        values = self.repo.valuations(self.account)
        self.assertEqual([item.value for item in values], [120_000, 110_000])
        at = self.repo.valuation_at(self.account, "2026-02-15")
        self.assertIsNotNone(at)
        self.assertEqual(at.value, 110_000)

    def test_update_valuation_moves_date_and_rejects_duplicate(self) -> None:
        first = self.repo.set_valuation(self.account, "2026-01-31", 110_000)
        second = self.repo.set_valuation(self.account, "2026-02-28", 120_000)
        self.repo.update_valuation(first, "2026-02-27", 115_000, "调整日期")
        values = self.repo.valuations(self.account)
        self.assertEqual([item.value for item in values], [120_000, 115_000])
        with self.assertRaises(ValueError):
            self.repo.update_valuation(second, "2026-02-27", 130_000)
        self.assertEqual(self._balance(), 120_000)

    def test_rejects_non_investment_and_future_date(self) -> None:
        cash = self.repo.add_account("测试零钱", "cash", 0)
        with self.assertRaises(ValueError):
            self.repo.set_valuation(cash, "2026-01-31", 100)
        with self.assertRaises(ValueError):
            self.repo.set_valuation(self.account, "2999-01-01", 100)

    def test_account_with_valuation_is_locked(self) -> None:
        self.repo.set_valuation(self.account, "2026-02-01", 200_000)
        with self.assertRaises(ValueError):
            self.repo.update_account(self.account, opening_balance=1)
        with self.assertRaises(ValueError):
            self.repo.update_account(self.account, type_="cash")
        with self.assertRaises(ValueError):
            self.repo.update_account(self.account, currency="USD")

    def test_transfer_after_valuation_changes_balance(self) -> None:
        bank = self.repo.add_account("银行卡", "debit", 10_000)
        self.repo.set_valuation(self.account, "2026-02-01", 200_000)
        self.repo.add_transaction(
            date="2026-02-10",
            kind="transfer",
            amount=5_000,
            account_id=bank,
            to_account_id=self.account,
        )
        self.assertEqual(self._balance(), 205_000)

    def test_service_emits_and_net_worth_uses_valuation(self) -> None:
        service = FinanceService(self.repo)
        emitted: list[int] = []
        service.changed.connect(lambda: emitted.append(1))
        service.set_valuation(self.account, today(), 300_000)
        self.assertEqual(emitted, [1])
        self.assertEqual(service.repo.net_worth().assets, 300_000)
        self.assertEqual(len(service.valuations(self.account)), 1)


if __name__ == "__main__":
    unittest.main()
