from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class V40Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "v40.db")
        self.repo = Repository(self.db)
        self.account = self.repo.accounts()[0]
        self.repo.update_account(self.account.id, opening_balance=1_000_000)
        self.service = FinanceService(self.repo)
        self.expense = self.repo.categories("expense")
        self.income = self.repo.categories("income")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _clear_undo(self) -> None:
        with self.db.conn:
            self.db.conn.execute("DELETE FROM undo_log")

    def _add(self, *, kind="expense", category=None, amount=10_000, account_id=None):
        return self.service.add_transaction(
            date="2026-10-30",
            kind=kind,
            amount=amount,
            account_id=account_id or self.account.id,
            category_id=category.id if category else None,
            payee="bulk test",
        )

    def test_schema_v11_has_returns_and_undo_log(self) -> None:
        with self.db.conn:
            version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row["name"]
                for row in self.db.conn.execute("PRAGMA table_info(holdings)")
            }
            tables = {
                row["name"]
                for row in self.db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(version, 13)
        self.assertIn("realized_profit", columns)
        self.assertIn("dividends", columns)
        self.assertIn("undo_log", tables)

    def test_holding_realized_and_dividends_summary(self) -> None:
        broker = self.repo.add_account("Broker", "investment", 0)
        self.repo.add_holding(
            broker,
            "ETF",
            symbol="510300",
            quantity_units=1_000_000,
            cost_price=10_000,
            price=12_000,
            realized_profit=500,
            dividends=300,
        )
        holding = self.repo.holdings(broker)[0]
        self.assertEqual(holding.total_profit, 2_800)
        summary = self.repo.holdings_summary()
        self.assertEqual(summary.realized, 500)
        self.assertEqual(summary.dividends, 300)
        self.assertEqual(summary.total_profit, 2_800)

    def test_bulk_update_and_undo(self) -> None:
        first = self._add(category=self.expense[0])
        second = self._add(category=self.expense[0])
        self._clear_undo()
        result = self.service.bulk_update_transactions(
            [first, second],
            category_id=self.expense[1].id,
            add_tags=["bulk", "review"],
        )
        self.assertEqual(result.updated, 2)
        self.assertEqual(self.repo.get_transaction(first).category_id, self.expense[1].id)
        self.assertEqual(
            {tag.name for tag in self.repo.get_transaction(second).tags},
            {"bulk", "review"},
        )
        self.assertTrue(self.service.has_undo())
        message = self.service.undo_last()
        self.assertIn("2", message)
        self.assertEqual(self.repo.get_transaction(first).category_id, self.expense[0].id)
        self.assertEqual(self.repo.get_transaction(second).tags, ())
        self.assertFalse(self.service.has_undo())

    def test_bulk_skips_transfer_and_split(self) -> None:
        other = self.repo.add_account("Other", "cash", 0)
        transfer = self.service.add_transaction(
            date="2026-10-30",
            kind="transfer",
            amount=1_000,
            account_id=self.account.id,
            to_account_id=other,
        )
        split = self._add(category=self.expense[0])
        split_txn = self.repo.get_transaction(split)
        self.service.update_transaction(
            split,
            date=split_txn.date,
            kind=split_txn.kind,
            amount=split_txn.amount,
            account_id=split_txn.account_id,
            category_id=split_txn.category_id,
            splits=[
                (self.expense[0].id, 5_000, ""),
                (self.expense[1].id, 5_000, ""),
            ],
        )
        self._clear_undo()
        result = self.service.bulk_update_transactions(
            [transfer, split],
            category_id=self.expense[1].id,
        )
        self.assertEqual(result.updated, 0)
        self.assertFalse(self.service.has_undo())

    def test_negative_dividend_is_rejected(self) -> None:
        broker = self.repo.add_account("Broker", "investment", 0)
        with self.assertRaises(ValueError):
            self.repo.add_holding(
                broker,
                "ETF",
                quantity_units=1_000_000,
                cost_price=10_000,
                price=10_000,
                dividends=-1,
            )


if __name__ == "__main__":
    unittest.main()
