"""Reliability checks: migration, index repair and restore drills."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finboard_fluent.core import backup as backup_module
from finboard_fluent.core import database as database_module
from finboard_fluent.core.backup import (
    create_backup,
    looks_like_index_problem,
    quick_check,
    repair_indexes,
    restore_backup,
)
from finboard_fluent.core.database import Database, SCHEMA_VERSION
from finboard_fluent.core.repository import Repository


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "reliability.db"
        self.db = Database(self.path)
        self.repo = Repository(self.db)
        self.account = self.repo.add_account("工资卡", "debit", 100_000)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_healthy_database_and_noop_repair(self) -> None:
        ok, detail = quick_check(self.db)
        self.assertTrue(ok, detail)
        self.assertTrue(repair_indexes(self.db)[0])

    def test_index_problem_detection_is_conservative(self) -> None:
        self.assertTrue(looks_like_index_problem("wrong # of entries in index idx_a"))
        self.assertTrue(looks_like_index_problem("索引损坏"))
        self.assertFalse(looks_like_index_problem("database disk image is malformed"))

    def test_repair_only_runs_for_index_failures(self) -> None:
        with patch.object(
            backup_module,
            "quick_check",
            side_effect=[(False, "database disk image is malformed")],
        ):
            ok, detail = repair_indexes(self.db)
        self.assertFalse(ok)
        self.assertIn("malformed", detail)

    def test_repair_rebuilds_index_then_verifies(self) -> None:
        with (
            patch.object(
                backup_module,
                "quick_check",
                side_effect=[
                    (False, "wrong # of entries in index idx_transactions_refund"),
                    (True, ""),
                ],
            ),
            patch.object(backup_module, "create_backup") as safety,
        ):
            ok, detail = repair_indexes(self.db)
        self.assertTrue(ok, detail)
        safety.assert_called_once()

    def test_restore_drill_round_trip(self) -> None:
        self.repo.add_transaction(
            date="2026-11-01", kind="expense", amount=1_000,
            account_id=self.account, category_id=self.repo.categories("expense")[0].id,
            payee="咖啡",
        )
        snapshot = create_backup(self.db, keep=5)
        self.repo.add_transaction(
            date="2026-11-02", kind="expense", amount=2_000,
            account_id=self.account, category_id=self.repo.categories("expense")[0].id,
            payee="午餐",
        )
        self.assertEqual(len(self.repo.transactions()), 2)
        restore_backup(self.db, snapshot)
        self.assertEqual(len(self.repo.transactions()), 1)
        self.assertTrue(quick_check(self.db)[0])

    def test_schema_14_database_migrates_to_current(self) -> None:
        raw_path = Path(self.tmp.name) / "legacy.db"
        conn = sqlite3.connect(raw_path)
        try:
            for version in range(1, 15):
                conn.executescript(getattr(database_module, f"SCHEMA_V{version}"))
            conn.execute("PRAGMA user_version = 14")
            conn.commit()
        finally:
            conn.close()
        legacy = Database(raw_path)
        try:
            version = legacy.conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            tables = {
                row[0]
                for row in legacy.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("term_deposits", tables)
            self.assertIn("debts", tables)
            self.assertIn("planned_transactions", tables)
            self.assertIn("receivables", tables)
            columns = {
                row[1]
                for row in legacy.conn.execute("PRAGMA table_info(holdings)")
            }
            self.assertIn("asset_class", columns)
            self.assertIn("region", columns)
            self.assertTrue(quick_check(legacy)[0])
        finally:
            legacy.close()


if __name__ == "__main__":
    unittest.main()
