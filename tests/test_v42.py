"""Tests for the 4.2 undo, refund, category-rule and backup features."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class V42Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.tmp.name) / "v42.db")
        self.repo = Repository(self.db)
        self.account_id = self.repo.add_account("储蓄卡", "debit", 1_000_000)
        self.expense = self.repo.categories("expense")
        self.income = self.repo.categories("income")
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _add(
        self,
        *,
        kind: str = "expense",
        amount: int = 10_000,
        category=None,
        payee: str = "",
        date: str = "2026-10-05",
        refund_of_id: int | None = None,
    ) -> int:
        return self.service.add_transaction(
            date=date,
            kind=kind,
            amount=amount,
            account_id=self.account_id,
            category_id=(category or self.expense[0]).id,
            payee=payee,
            refund_of_id=refund_of_id,
        )

    def test_schema_v13_has_refunds_and_rules(self) -> None:
        self.assertEqual(
            self.db.conn.execute("PRAGMA user_version").fetchone()[0], 14
        )
        columns = {
            row["name"]
            for row in self.db.conn.execute("PRAGMA table_info(transactions)")
        }
        tables = {
            row["name"]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("refund_of_id", columns)
        self.assertIn("category_rules", tables)

    def test_refund_reduces_expense_without_inflating_income(self) -> None:
        expense_id = self._add(amount=10_000, payee="京东")
        self._add(
            kind="income",
            amount=3_000,
            category=self.income[0],
            payee="京东",
            date="2026-10-06",
            refund_of_id=expense_id,
        )

        stats = self.repo.month_stats("2026-10")
        self.assertEqual(stats.expense, 7_000)
        self.assertEqual(stats.income, 0)

        breakdown = {item.category_id: item.amount for item in self.repo.category_breakdown("2026-10")}
        self.assertEqual(breakdown[self.expense[0].id], 7_000)

        payees = {item.payee: item.amount for item in self.repo.top_payees("2026-10")}
        self.assertEqual(payees["京东"], 7_000)

        trend = self.repo.trend(months=12, end_month="2026-10")
        self.assertEqual(trend[-1].expense, 7_000)
        self.assertEqual(trend[-1].income, 0)

    def test_refund_guards_and_delete_order(self) -> None:
        expense_id = self._add(amount=10_000, payee="京东")
        with self.assertRaises(ValueError):
            self._add(
                kind="income",
                amount=11_000,
                category=self.income[0],
                refund_of_id=expense_id,
            )

        income_id = self._add(kind="income", amount=2_000, category=self.income[0])
        with self.assertRaises(ValueError):
            self._add(
                kind="income",
                amount=1_000,
                category=self.income[0],
                refund_of_id=income_id,
            )

        refund_id = self._add(
            kind="income",
            amount=3_000,
            category=self.income[0],
            refund_of_id=expense_id,
        )
        with self.assertRaises(ValueError):
            self.service.delete_transaction(expense_id)
        with self.assertRaises(ValueError):
            self.service.update_transaction(
                expense_id,
                date="2026-10-05",
                kind="expense",
                amount=2_000,
                account_id=self.account_id,
                category_id=self.expense[0].id,
            )

        self.service.delete_transaction(refund_id)
        self.service.delete_transaction(expense_id)
        with self.assertRaises(ValueError):
            self.repo.get_transaction(expense_id)

    def test_undo_add_update_delete_and_metadata(self) -> None:
        transaction_id = self._add(payee="旧商户")
        self.assertTrue(self.service.has_undo())
        self.assertIn("新增", self.service.undo_last())
        with self.assertRaises(ValueError):
            self.repo.get_transaction(transaction_id)

        transaction_id = self._add(payee="旧商户")
        self.service.update_transaction(
            transaction_id,
            date="2026-10-05",
            kind="expense",
            amount=10_000,
            account_id=self.account_id,
            category_id=self.expense[0].id,
            payee="新商户",
        )
        self.assertIn("修改", self.service.undo_last())
        self.assertEqual(self.repo.get_transaction(transaction_id).payee, "旧商户")

        self.service.delete_transaction(transaction_id)
        self.assertIn("恢复", self.service.undo_last())
        self.assertEqual(self.repo.get_transaction(transaction_id).payee, "旧商户")

        self.service.set_transaction_metadata(transaction_id, tags=["待报销"])
        self.assertEqual(
            {tag.name for tag in self.repo.get_transaction(transaction_id).tags},
            {"待报销"},
        )
        self.assertIn("标签", self.service.undo_last())
        self.assertEqual(self.repo.get_transaction(transaction_id).tags, ())

    def test_undo_keeps_refund_link(self) -> None:
        expense_id = self._add(amount=10_000)
        refund_id = self._add(
            kind="income",
            amount=3_000,
            category=self.income[0],
            refund_of_id=expense_id,
        )
        self.service.update_transaction(
            refund_id,
            date="2026-10-05",
            kind="income",
            amount=2_500,
            account_id=self.account_id,
            category_id=self.income[0].id,
            refund_of_id=expense_id,
        )
        self.service.undo_last()
        refund = self.repo.get_transaction(refund_id)
        self.assertEqual(refund.amount, 3_000)
        self.assertEqual(refund.refund_of_id, expense_id)
        self.assertTrue(refund.is_refund)

    def test_category_rule_matching_learning_and_tags(self) -> None:
        first = self.service.add_category_rule(
            "京东", "expense", self.expense[0].id, ["网购"]
        )
        second = self.service.add_category_rule(
            "京东商城", "expense", self.expense[1].id, ["商城"]
        )
        matched = self.service.match_category_rule("京东商城自营", "expense")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, second)
        self.assertIsNone(self.service.match_category_rule("美团", "expense"))

        transaction_id = self._add(payee="京东自营", category=self.expense[1])
        self.assertEqual(self.service.apply_rule_tags_to_history(first), 1)
        self.assertEqual(
            {tag.name for tag in self.repo.get_transaction(transaction_id).tags},
            {"网购"},
        )
        self.service.record_rule_hit(first)
        self.assertEqual(self.repo.get_category_rule(first).hit_count, 1)

        for _ in range(2):
            self._add(payee="星巴克", category=self.expense[0])
        self.assertGreaterEqual(self.service.learn_category_rules(), 1)
        learned = self.service.match_category_rule("星巴克咖啡", "expense")
        self.assertIsNotNone(learned)
        self.assertEqual(learned.category_id, self.expense[0].id)

    def test_backup_integrity_and_restore(self) -> None:
        self._add(amount=1_000)
        backup = self.service.create_backup(keep=5)
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.parent.name, "backups")
        self.assertIn(backup, self.service.backups())
        ok, _ = self.service.check_integrity()
        self.assertTrue(ok)

        self._add(amount=2_000)
        self.assertEqual(self.repo.count_transactions(), 2)
        self.service.restore_backup(backup)
        self.assertEqual(self.repo.count_transactions(), 1)
        ok, _ = self.service.check_integrity()
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
