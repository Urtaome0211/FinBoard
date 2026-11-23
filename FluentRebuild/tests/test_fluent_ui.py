"""Smoke tests for the Fluent shell and its parity with the 5.0 pages."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from finboard_fluent.core.database import Database  # noqa: E402
from finboard_fluent.core.repository import Repository  # noqa: E402
from finboard_fluent.core.service import FinanceService  # noqa: E402
from finboard_fluent.i18n import set_language  # noqa: E402
from finboard_fluent.ui.fluent_controls import DateEdit, LineEdit  # noqa: E402
from finboard_fluent.ui.dialogs.prompt import TextPromptDialog  # noqa: E402
from finboard_fluent.ui.dialogs.investment_trade import TradeDialog  # noqa: E402
from finboard_fluent.ui.main_window import MainWindow  # noqa: E402


class FluentShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "fluent.db")
        self.repo = Repository(self.db)
        self.account = self.repo.add_account("工资卡", "debit", 100_000)
        self.service = FinanceService(self.repo)
        self.settings = QSettings("FinBoardFluentTest", "FinBoardFluentTest")
        self.settings.clear()
        set_language("zh")
        self.window = MainWindow(self.service, self.settings)
        self.window.resize(1400, 900)

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        set_language("zh")
        self.db.close()
        self.tmp.cleanup()

    def test_all_pages_and_navigation(self) -> None:
        self.assertEqual(len(self.window.pages), 15)
        for key in self.window.pages:
            self.window.navigate(key)
            self.assertIs(self.window.stackedWidget.currentWidget(), self.window.pages[key])
        self.assertIsNotNone(self.window.search)
        self.assertIsNotNone(self.window.add_button)
        self.assertIsNotNone(self.window.theme_button)
        self.window.current_key = "dashboard"
        self.window.switchTo(self.window.pages["reports"])
        self.app.processEvents()
        self.assertEqual(self.window.current_key, "reports")

    def test_tray_and_reminders_default_off(self) -> None:
        page = self.window.pages["settings"]
        self.assertFalse(page.tray_control.value())
        self.assertFalse(page.reminders_control.value())
        self.assertIsNone(self.window._tray)

    def test_language_switch_updates_shell(self) -> None:
        page = self.window.pages["settings"]
        page.language_control.set_value("en", emit=True)
        self.app.processEvents()
        self.window = MainWindow._live
        self.assertIsNotNone(self.window)
        self.assertEqual(
            self.window.navigationInterface.widget("page_dashboard").text(), "Overview"
        )
        self.assertEqual(
            self.window.navigationInterface.widget("page_settings").text(), "Settings"
        )
        self.assertEqual(self.window.add_button.text(), "Add transaction")
        labels = [label.text() for label in self.window.pages["dashboard"].findChildren(QLabel)]
        self.assertIn("Overview", labels)

        page = self.window.pages["settings"]
        page.language_control.set_value("zh", emit=True)
        self.app.processEvents()
        self.window = MainWindow._live
        self.assertIsNotNone(self.window)
        self.assertEqual(
            self.window.navigationInterface.widget("page_dashboard").text(), "总览"
        )
        labels = [label.text() for label in self.window.pages["dashboard"].findChildren(QLabel)]
        self.assertIn("总览", labels)
        self.assertNotIn("Overview", labels)

    def test_theme_toggle_keeps_pages_alive(self) -> None:
        self.window.set_theme("dark")
        self.app.processEvents()
        self.assertEqual(self.window.backgroundColor.name(), "#202020")
        self.window.navigate("dashboard")
        self.assertIs(self.window.stackedWidget.currentWidget(), self.window.pages["dashboard"])
        self.window.set_theme("light")
        self.assertEqual(self.window.backgroundColor.name(), "#f0f4f9")

    def test_fluent_date_and_line_edit(self) -> None:
        edit = DateEdit(QDate(2026, 11, 6))
        edit.setDisplayFormat("yyyy-MM-dd")
        self.assertEqual(edit.getDate(), QDate(2026, 11, 6))
        line = LineEdit("hello")
        self.assertEqual(line.text(), "hello")

    def test_trade_dialog_existing_or_manual_buy(self) -> None:
        account_id = self.repo.add_account("证券账户", "investment", 0)
        self.repo.record_investment_trade(
            account_id,
            kind="buy",
            symbol="AAPL",
            name="苹果",
            trade_date="2026-11-01",
            quantity_units=1_000_000,
            price=20_000,
        )
        account = self.repo.get_account(account_id)
        dialog = TradeDialog(self.service, account, kind="buy")
        self.assertEqual(dialog.holding_combo.count(), 2)
        self.assertEqual(dialog.holding_combo.itemText(0), "手动填写新持仓")
        self.assertIsNone(dialog.holding_combo.itemData(0))
        self.assertIn("苹果", dialog.holding_combo.itemText(1))

        dialog.holding_combo.setCurrentIndex(1)
        self.app.processEvents()
        self.assertEqual(dialog.name_input.text(), "苹果")
        self.assertEqual(dialog.symbol_input.text(), "AAPL")
        self.assertEqual(dialog.price_input.text(), "200.00")
        self.assertEqual(dialog.quantity_input.text(), "")
        self.assertTrue(dialog.name_input.isReadOnly())
        self.assertTrue(dialog.symbol_input.isReadOnly())

        dialog.holding_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(dialog.name_input.text(), "")
        self.assertEqual(dialog.symbol_input.text(), "")
        self.assertFalse(dialog.name_input.isReadOnly())
        self.assertFalse(dialog.symbol_input.isReadOnly())

        dialog.holding_combo.setCurrentIndex(1)
        self.app.processEvents()
        dialog.quantity_input.setText("2")
        dialog.price_input.setText("210.00")
        dialog._save()
        self.app.processEvents()
        holdings = self.service.holdings(account_id)
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0].quantity_units, 3_000_000)
        dialog.deleteLater()
        self.app.processEvents()

    def test_fluent_text_prompt(self) -> None:
        dialog = TextPromptDialog(
            None, title="保存为模板", label="模板名称", default="午餐"
        )
        self.assertEqual(dialog.value(), "午餐")
        dialog.input.setText("  咖啡  ")
        self.assertEqual(dialog.value(), "咖啡")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
