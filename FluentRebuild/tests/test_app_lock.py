from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.security import encrypt_database, unlock_key
from finboard_fluent.core.service import FinanceService
from finboard_fluent.ui.localize import install_localizer
from finboard_fluent.ui.main_window import MainWindow


class AppLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        install_localizer(cls.app)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "finboard.db"
        db = Database(self.path)
        db.conn.execute("SELECT 1")
        db.close()
        encrypt_database(self.path, "pw123456")
        self.key = unlock_key(
            __import__("finboard_fluent.core.security", fromlist=["load_config"]).load_config(self.path),
            "pw123456",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lock_overlay_unlock(self) -> None:
        db = Database(self.path, encryption_key=self.key)
        service = FinanceService(Repository(db), "CNY")
        window = MainWindow(
            service,
            QSettings("FinBoard", "FinBoard"),
            language="zh",
            auto_refresh_rates=False,
            auto_refresh_quotes=False,
        )
        try:
            window.lock_now()
            self.assertIsNotNone(window._lock_overlay)
            window._try_unlock("wrong")
            self.assertIsNotNone(window._lock_overlay)
            window._try_unlock("pw123456")
            self.assertIsNone(window._lock_overlay)
        finally:
            window.shutdown()
            window.close()
            db.close()


if __name__ == "__main__":
    unittest.main()
