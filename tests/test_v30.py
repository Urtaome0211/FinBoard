from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path

from finboard.core import csv_io, exporters
from finboard.core.database import Database
from finboard.core.models import CsvRule, TransactionFilter
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class V30Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = Database(self.root / "v30.db")
        self.repo = Repository(self.db)
        self.account = self.repo.accounts()[0]
        self.repo.update_account(self.account.id, opening_balance=1_000_000)
        self.category = self.repo.categories("expense")[0]
        self.service = FinanceService(self.repo)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_v10(self) -> None:
        with self.db.conn:
            version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in self.db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(version, 10)
        for name in (
            "tags",
            "transaction_tags",
            "transaction_splits",
            "attachments",
            "csv_import_rules",
        ):
            self.assertIn(name, tables)

    def test_splits_and_tags_round_trip(self) -> None:
        categories = self.repo.categories("expense")
        txn_id = self.service.add_transaction(
            date="2026-10-29",
            kind="expense",
            amount=10_000,
            account_id=self.account.id,
            category_id=categories[0].id,
            payee="split test",
            splits=[(categories[0].id, 4_000, "part a"), (categories[1].id, 6_000, "part b")],
            tags=["travel", "reimburse"],
        )
        txn = self.repo.get_transaction(txn_id)
        self.assertTrue(txn.has_splits)
        self.assertEqual(txn.split_total, 10_000)
        self.assertEqual({x.name for x in txn.tags}, {"travel", "reimburse"})
        breakdown = {x.name: x.amount for x in self.repo.category_breakdown("2026-10", "expense")}
        self.assertEqual(breakdown[categories[0].name], 4_000)
        self.assertEqual(breakdown[categories[1].name], 6_000)
        self.assertEqual(
            len(self.repo.transactions(TransactionFilter(tag_id=txn.tags[0].id))), 1
        )

    def test_split_total_must_match(self) -> None:
        with self.assertRaises(ValueError):
            self.service.add_transaction(
                date="2026-10-29",
                kind="expense",
                amount=10_000,
                account_id=self.account.id,
                category_id=self.category.id,
                splits=[(self.category.id, 9_999, "")],
            )

    def test_attachment_copy_and_delete(self) -> None:
        old = os.environ.get("FINBOARD_DATA_DIR")
        os.environ["FINBOARD_DATA_DIR"] = str(self.root / "data")
        try:
            txn_id = self.service.add_transaction(
                date="2026-10-29",
                kind="expense",
                amount=1_000,
                account_id=self.account.id,
                category_id=self.category.id,
            )
            source = self.root / "receipt.txt"
            source.write_text("receipt", encoding="utf-8")
            attachment_id = self.service.add_attachment(txn_id, source)
            attachment = self.service.attachments(txn_id)[0]
            self.assertTrue(self.service.attachment_file(attachment).exists())
            self.service.delete_attachment(attachment_id)
            self.assertEqual(self.service.attachments(txn_id), [])
            self.assertFalse(self.service.attachment_file(attachment).exists())
        finally:
            if old is None:
                os.environ.pop("FINBOARD_DATA_DIR", None)
            else:
                os.environ["FINBOARD_DATA_DIR"] = old

    def test_csv_rule_and_duplicate_detection(self) -> None:
        csv_path = self.root / "custom.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["交易时间", "方向", "金额", "户名", "分类", "商户"])
            writer.writerow(["2026-10-29", "支出", "12.30", self.account.name, self.category.name, "咖啡"])
        rule = CsvRule(
            id=0,
            name="custom",
            mapping={
                "date": "交易时间",
                "kind": "方向",
                "amount": "金额",
                "account": "户名",
                "category": "分类",
                "payee": "商户",
            },
        )
        first = csv_io.import_csv(self.repo, csv_path, rule=rule)
        second = csv_io.import_csv(self.repo, csv_path, rule=rule)
        self.assertEqual(first.imported, 1)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.duplicates, 1)

    def test_excel_export(self) -> None:
        target = self.root / "report.xlsx"
        exporters.export_excel(self.repo, target, "2026-10")
        self.assertTrue(target.exists())
        self.assertGreater(target.stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
