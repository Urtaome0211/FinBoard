from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.csv_io import import_csv
from finboard_fluent.core.database import Database
from finboard_fluent.core.dates import shift_month, today_iso
from finboard_fluent.core.insights import financial_health
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.service import FinanceService


class AutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.account = self.repo.get_account(self.repo.add_account("工资卡", "debit", 1_000_000))
        self.expense = self.repo.categories("expense")[0]
        self.income = self.repo.categories("income")[0]
        self.service = FinanceService(self.repo, "CNY")

    def tearDown(self) -> None:
        self.db.close()
        try:
            self.tmp.cleanup()
        except PermissionError:
            pass

    def test_csv_import_applies_rule_and_tags(self) -> None:
        self.repo.add_category_rule("星巴克", "expense", self.expense.id, ["咖啡"])
        path = Path(self.tmp.name) / "alipay.csv"
        path.write_text(
            "交易时间,收/支,金额,交易对方,商品说明\n"
            "2026-11-01 09:30:00,支出,28.00,星巴克,拿铁\n",
            encoding="utf-8",
        )
        result = import_csv(self.repo, path, default_account_id=self.account.id)
        self.assertEqual(result.imported, 1)
        txn = self.repo.transactions()[0]
        self.assertEqual(txn.category_id, self.expense.id)
        self.assertEqual(txn.tag_names, ["咖啡"])
        rule = self.repo.match_category_rule("星巴克", "expense")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.hit_count, 1)

    def test_post_all_due_recurring_posts_each_due_rule_once(self) -> None:
        rule_id = self.repo.add_recurring(
            name="房租",
            kind="expense",
            amount=150_000,
            account_id=self.account.id,
            category_id=self.expense.id,
            start_date=today_iso(),
        )
        self.assertEqual(len(self.repo.due_recurring()), 1)
        count = self.service.post_all_due_recurring()
        self.assertEqual(count, 1)
        self.assertEqual(len(self.repo.due_recurring()), 0)
        self.assertEqual(len(self.repo.transactions()), 1)
        self.assertGreater(self.repo.get_recurring(rule_id).next_date, today_iso())

    def test_financial_health_uses_existing_aggregates(self) -> None:
        month = shift_month(today_iso()[:7], -1)
        for delta in range(3):
            m = shift_month(month, -delta)
            self.repo.add_transaction(
                date=f"{m}-05",
                kind="expense",
                amount=150_000,
                account_id=self.account.id,
                category_id=self.expense.id,
                payee="房租",
            )
            self.repo.add_transaction(
                date=f"{m}-10",
                kind="income",
                amount=500_000,
                account_id=self.account.id,
                category_id=self.income.id,
                payee="工资",
            )
        self.repo.upsert_budget(today_iso()[:7], 0, 200_000)
        health = financial_health(self.repo, today_iso()[:7])
        self.assertGreaterEqual(health.score, 0)
        self.assertLessEqual(health.score, 100)
        self.assertIn(health.grade, {"A", "B", "C", "D"})
        self.assertGreaterEqual(health.emergency_months, 0)
        self.assertTrue(health.has_budget)


if __name__ == "__main__":
    unittest.main()
