from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.service import FinanceService


class TransactionTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo, "CNY")
        self.account = self.repo.add_account("工资卡", "debit", 500_000)
        self.category = self.repo.categories("expense")[0].id

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_and_crud(self) -> None:
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 19)
        template_id = self.repo.add_transaction_template(
            "午餐",
            kind="expense",
            amount=3_500,
            account_id=self.account,
            category_id=self.category,
            payee="食堂",
            note="工作日",
        )
        template = self.repo.get_transaction_template(template_id)
        self.assertEqual(template.name, "午餐")
        self.assertEqual(template.amount, 3_500)
        self.assertEqual(template.category_name, "餐饮")
        self.assertEqual(template.account_name, "工资卡")
        self.assertEqual(template.title, "食堂")
        self.assertEqual(len(self.repo.transaction_templates()), 1)

        self.repo.update_transaction_template(
            template_id, name="晚餐", amount=4_200, payee=""
        )
        updated = self.repo.get_transaction_template(template_id)
        self.assertEqual(updated.name, "晚餐")
        self.assertEqual(updated.amount, 4_200)
        self.assertEqual(updated.title, "餐饮")

        self.repo.delete_transaction_template(template_id)
        self.assertEqual(self.repo.transaction_templates(), [])

    def test_transfer_template_validation(self) -> None:
        target = self.repo.add_account("储蓄卡", "debit", 100_000)
        template_id = self.repo.add_transaction_template(
            "还信用卡",
            kind="transfer",
            amount=50_000,
            account_id=self.account,
            to_account_id=target,
        )
        template = self.repo.get_transaction_template(template_id)
        self.assertEqual(template.kind, "transfer")
        self.assertEqual(template.to_account_name, "储蓄卡")
        with self.assertRaisesRegex(ValueError, "转入账户"):
            self.repo.add_transaction_template(
                "无目标",
                kind="transfer",
                account_id=self.account,
            )
        with self.assertRaisesRegex(ValueError, "不能相同"):
            self.repo.add_transaction_template(
                "同账户",
                kind="transfer",
                account_id=self.account,
                to_account_id=self.account,
            )
        with self.assertRaisesRegex(ValueError, "分类"):
            self.repo.add_transaction_template(
                "转账分类",
                kind="transfer",
                category_id=self.category,
                account_id=self.account,
                to_account_id=target,
            )

    def test_category_kind_and_name_validation(self) -> None:
        income = self.repo.categories("income")[0].id
        with self.assertRaisesRegex(ValueError, "不匹配"):
            self.repo.add_transaction_template(
                "错误分类",
                kind="expense",
                category_id=income,
                account_id=self.account,
            )
        with self.assertRaisesRegex(ValueError, "名称"):
            self.repo.add_transaction_template(
                "  ",
                kind="expense",
                account_id=self.account,
            )
        with self.assertRaisesRegex(ValueError, "系统账户"):
            system = self.repo.deposit_account("CNY")
            self.repo.add_transaction_template(
                "系统账户",
                kind="expense",
                account_id=system.id,
            )

    def test_service_and_clear(self) -> None:
        template_id = self.service.add_transaction_template(
            "咖啡",
            kind="expense",
            amount=2_800,
            account_id=self.account,
            category_id=self.category,
        )
        self.assertEqual(len(self.service.transaction_templates()), 1)
        event = []
        self.service.changed.connect(lambda: event.append(True))
        self.service.delete_transaction_template(template_id)
        self.assertTrue(event)
        self.assertEqual(self.service.transaction_templates(), [])

        self.service.add_transaction_template(
            "保留检查",
            kind="expense",
            account_id=self.account,
        )
        self.repo.clear_all()
        self.assertEqual(self.repo.transaction_templates(), [])


if __name__ == "__main__":
    unittest.main()
