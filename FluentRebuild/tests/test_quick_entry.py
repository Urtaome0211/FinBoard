"""Tests for the compact quick-entry window."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.service import FinanceService
from finboard_fluent.ui.dialogs.quick_entry import QuickEntryDialog


class QuickEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo, "CNY")
        self.account = self.repo.add_account("工资卡", "debit", 100_000)
        self.category = self.repo.categories("expense")[0]

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_saves_compact_expense(self) -> None:
        dialog = QuickEntryDialog(self.service)
        dialog.amount_input.setText("12.34")
        dialog.payee_input.setText("咖啡")
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData(self.category.id)
        )
        dialog._save()
        rows = self.repo.transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].amount, 1234)
        self.assertEqual(rows[0].payee, "咖啡")
        self.assertEqual(rows[0].account_id, self.account)

    def test_kind_switch_reloads_categories(self) -> None:
        dialog = QuickEntryDialog(self.service)
        income = self.repo.categories("income")[0]
        dialog.kind_control.set_value("income", emit=True)
        self.assertEqual(dialog.category_combo.currentData(), income.id)


if __name__ == "__main__":
    unittest.main()
