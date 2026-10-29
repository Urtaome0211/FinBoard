"""Running-balance tests for the transaction ledger."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.repository import Repository


class TransactionBalanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "balances.db")
        self.repo = Repository(self.db)
        self.bank = self.repo.add_account("银行卡", "debit", 100_000)
        self.wallet = self.repo.add_account("零钱", "debit", 5_000)
        self.expense_category = self.repo.categories("expense")[0].id
        self.income_category = self.repo.categories("income")[0].id

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _add(self, **fields):
        return self.repo.add_transaction(**fields)

    def test_ledger_running_balance_and_transfer(self) -> None:
        income = self._add(
            date="2026-10-01",
            kind="income",
            amount=50_000,
            account_id=self.bank,
            category_id=self.income_category,
        )
        expense = self._add(
            date="2026-10-02",
            kind="expense",
            amount=20_000,
            account_id=self.bank,
            category_id=self.expense_category,
        )
        transfer = self._add(
            date="2026-10-03",
            kind="transfer",
            amount=30_000,
            account_id=self.bank,
            to_account_id=self.wallet,
        )
        spend = self._add(
            date="2026-10-04",
            kind="expense",
            amount=10_000,
            account_id=self.wallet,
            category_id=self.expense_category,
        )

        balances = self.repo.transaction_balances(
            [income, expense, transfer, spend]
        )
        self.assertEqual(balances[income].account_balance, 150_000)
        self.assertEqual(balances[expense].account_balance, 130_000)
        self.assertEqual(balances[transfer].account_balance, 100_000)
        self.assertEqual(balances[transfer].to_account_balance, 35_000)
        self.assertEqual(balances[spend].account_balance, 25_000)

    def test_filtered_ids_still_use_full_history(self) -> None:
        self._add(
            date="2026-10-01",
            kind="income",
            amount=50_000,
            account_id=self.bank,
            category_id=self.income_category,
        )
        spend = self._add(
            date="2026-10-02",
            kind="expense",
            amount=10_000,
            account_id=self.bank,
            category_id=self.expense_category,
        )
        balances = self.repo.transaction_balances([spend])
        self.assertEqual(set(balances), {spend})
        self.assertEqual(balances[spend].account_balance, 140_000)

    def test_same_day_order_uses_id(self) -> None:
        first = self._add(
            date="2026-10-01",
            kind="expense",
            amount=100,
            account_id=self.bank,
            category_id=self.expense_category,
        )
        second = self._add(
            date="2026-10-01",
            kind="expense",
            amount=200,
            account_id=self.bank,
            category_id=self.expense_category,
        )
        balances = self.repo.transaction_balances([first, second])
        self.assertEqual(balances[first].account_balance, 99_900)
        self.assertEqual(balances[second].account_balance, 99_700)

    def test_withdrawal_fee_is_included(self) -> None:
        alipay = self.repo.add_account("支付宝钱包", "debit", 100_000)
        bank = self.repo.add_account("提现卡", "debit", 0)
        txn = self._add(
            date="2026-10-03",
            kind="transfer",
            amount=10_000,
            account_id=alipay,
            to_account_id=bank,
        )
        balances = self.repo.transaction_balances([txn])
        self.assertEqual(balances[txn].account_balance, 89_990)
        self.assertEqual(balances[txn].to_account_balance, 10_000)

    def test_valuation_is_the_end_of_day_baseline(self) -> None:
        stock = self.repo.add_account("证券账户", "investment", 100_000)
        self.repo.set_valuation(stock, "2026-10-01", 200_000)
        on_snapshot = self._add(
            date="2026-10-01",
            kind="income",
            amount=5_000,
            account_id=stock,
            category_id=self.income_category,
        )
        after_snapshot = self._add(
            date="2026-10-05",
            kind="expense",
            amount=10_000,
            account_id=stock,
            category_id=self.expense_category,
        )
        self.repo.set_valuation(stock, "2026-10-10", 250_000)
        after_second = self._add(
            date="2026-10-12",
            kind="expense",
            amount=20_000,
            account_id=stock,
            category_id=self.expense_category,
        )
        balances = self.repo.transaction_balances(
            [on_snapshot, after_snapshot, after_second]
        )
        self.assertEqual(balances[on_snapshot].account_balance, 200_000)
        self.assertEqual(balances[after_snapshot].account_balance, 190_000)
        self.assertEqual(balances[after_second].account_balance, 230_000)


if __name__ == "__main__":
    unittest.main()
