"""Smoke tests for the Fluent shell and its parity with the 5.0 pages."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from finboard_fluent.core.database import Database  # noqa: E402
from finboard_fluent.core.repository import Repository  # noqa: E402
from finboard_fluent.core.service import FinanceService  # noqa: E402
from finboard_fluent.i18n import set_language  # noqa: E402
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
        self.assertEqual(len(self.window.pages), 13)
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

    def test_language_switch_updates_shell(self) -> None:
        self.window = self.window.set_language("en")
        self.app.processEvents()
        self.assertEqual(
            self.window.navigationInterface.widget("page_dashboard").text(), "Overview"
        )
        self.assertEqual(
            self.window.navigationInterface.widget("page_settings").text(), "Settings"
        )
        self.assertEqual(self.window.add_button.text(), "Add transaction")
        labels = [label.text() for label in self.window.pages["dashboard"].findChildren(QLabel)]
        self.assertIn("Overview", labels)

        self.window = self.window.set_language("zh")
        self.app.processEvents()
        self.assertEqual(
            self.window.navigationInterface.widget("page_dashboard").text(), "总览"
        )
        labels = [label.text() for label in self.window.pages["dashboard"].findChildren(QLabel)]
        self.assertIn("总览", labels)
        self.assertNotIn("Overview", labels)

    def test_theme_toggle_keeps_pages_alive(self) -> None:
        self.window.set_theme("dark")
        self.app.processEvents()
        self.window.navigate("dashboard")
        self.assertIs(self.window.stackedWidget.currentWidget(), self.window.pages["dashboard"])
        self.window.set_theme("light")


if __name__ == "__main__":
    unittest.main()
