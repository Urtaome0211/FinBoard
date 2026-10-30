"""Recurring transactions and reconciliation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.repository import Repository, next_recurring_date


class V2TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.bank = self.repo.add_account("招商银行储蓄卡", "debit", 1_000_000)
        self.expense = self.repo.categories("expense")[0].id
        self.income = self.repo.categories("income")[0].id

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()


class RecurringTests(V2TestCase):
    def test_month_end_is_clamped(self) -> None:
        self.assertEqual(next_recurring_date("2026-01-31", "monthly"), "2026-02-28")
        self.assertEqual(next_recurring_date("2026-03-31", "monthly"), "2026-04-30")
        self.assertEqual(next_recurring_date("2024-02-29", "yearly"), "2025-02-28")

    def test_create_and_post_recurring(self) -> None:
        rule_id = self.repo.add_recurring(
            name="房租",
            kind="expense",
            amount=420_000,
            account_id=self.bank,
            category_id=self.expense,
            frequency="monthly",
            start_date="2026-10-01",
            payee="房东",
        )
        rule = self.repo.get_recurring(rule_id)
        self.assertEqual(rule.next_date, "2026-10-01")
        self.assertEqual(rule.title, "房租")

        due = self.repo.due_recurring("2026-10-30")
        self.assertEqual([item.id for item in due], [rule_id])
        txn_id = self.repo.post_recurring(rule_id)
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.kind, "expense")
        self.assertEqual(txn.amount, 420_000)
        self.assertEqual(txn.payee, "房东")
        self.assertEqual(self.repo.get_account(self.bank).balance, 580_000)
        self.assertEqual(self.repo.get_recurring(rule_id).next_date, "2026-11-01")
        self.assertEqual(len(self.repo.due_recurring("2026-10-30")), 0)

    def test_future_and_paused_rules_cannot_post(self) -> None:
        rule_id = self.repo.add_recurring(
            name="会员",
            kind="expense",
            amount=100,
            account_id=self.bank,
            category_id=self.expense,
            start_date="2026-12-01",
        )
        with self.assertRaisesRegex(ValueError, "尚未到期"):
            self.repo.post_recurring(rule_id)
        self.repo.set_recurring_active(rule_id, False)
        with self.assertRaisesRegex(ValueError, "已停用"):
            self.repo.post_recurring(rule_id)

    def test_rule_deactivates_after_end_date(self) -> None:
        rule_id = self.repo.add_recurring(
            name="短期订阅",
            kind="expense",
            amount=100,
            account_id=self.bank,
            category_id=self.expense,
            frequency="monthly",
            start_date="2026-10-01",
            end_date="2026-10-15",
        )
        self.repo.post_recurring(rule_id)
        rule = self.repo.get_recurring(rule_id)
        self.assertFalse(rule.active)
        self.assertEqual(rule.next_date, "2026-11-01")

    def test_update_start_resets_next_date(self) -> None:
        rule_id = self.repo.add_recurring(
            name="工资",
            kind="income",
            amount=1_800_000,
            account_id=self.bank,
            category_id=self.income,
            frequency="monthly",
            start_date="2026-10-01",
        )
        self.repo.update_recurring(
            rule_id,
            name="工资",
            kind="income",
            amount=1_900_000,
            account_id=self.bank,
            category_id=self.income,
            frequency="monthly",
            start_date="2026-12-01",
        )
        rule = self.repo.get_recurring(rule_id)
        self.assertEqual(rule.next_date, "2026-12-01")
        self.assertEqual(rule.amount, 1_900_000)


class ReconcileTests(V2TestCase):
    def test_reconcile_adjusts_balance_without_income(self) -> None:
        self.repo.add_transaction(
            date="2026-10-20",
            kind="expense",
            amount=10_000,
            account_id=self.bank,
            category_id=self.expense,
        )
        record = self.repo.reconcile_account(self.bank, 1_250_000, note="月末")
        self.assertEqual(record.difference, 260_000)
        account = self.repo.get_account(self.bank)
        self.assertEqual(account.adjustment, 260_000)
        self.assertEqual(account.balance, 1_250_000)
        self.assertEqual(self.repo.reconciliations(self.bank)[0].note, "月末")
        self.assertEqual(self.repo.month_stats("2026-10").expense, 10_000)

    def test_undo_reconciliation(self) -> None:
        record = self.repo.reconcile_account(self.bank, 1_200_000)
        self.repo.delete_reconciliation(record.id)
        account = self.repo.get_account(self.bank)
        self.assertEqual(account.adjustment, 0)
        self.assertEqual(account.balance, 1_000_000)
        self.assertEqual(self.repo.reconciliations(self.bank), [])

    def test_investment_accounts_use_valuations(self) -> None:
        investment = self.repo.add_account("基金账户", "investment", 100_000)
        with self.assertRaisesRegex(ValueError, "市值快照"):
            self.repo.reconcile_account(investment, 200_000)
        self.assertEqual(self.repo.get_account(investment).balance, 100_000)


if __name__ == "__main__":
    unittest.main()
