"""Application bootstrap: CLI flags, theme, database and main window."""

from __future__ import annotations

import argparse
import ctypes
import logging
import sqlite3
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __app_name__, __app_name_cn__, __version__
from .core.database import Database
from .core.models import TransactionFilter
from .core.paths import default_db_path, demo_db_path, log_path, portable_data_dir
from .core.repository import Repository
from .core.service import FinanceService
from .i18n import is_english, set_language, t
from .ui.icons import app_icon
from .ui.localize import apply_locale, install_localizer
from .ui.main_window import MainWindow
from .ui.theme import apply_theme

log = logging.getLogger("finboard")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="finboard",
        description="FinBoard · 财观 — 本地个人财务管理",
    )
    parser.add_argument("--demo", action="store_true", help="使用演示数据库")
    parser.add_argument(
        "--reset-demo", action="store_true", help="重建演示数据库后启动（隐含 --demo）"
    )
    parser.add_argument("--db", type=Path, help="指定数据库文件")
    parser.add_argument("--theme", choices=("light", "dark"), help="启动主题")
    parser.add_argument("--language", choices=("zh", "en"), help="启动语言")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _open_database(path: Path, *, allow_fallback: bool = True) -> tuple[Database, Path | None]:
    """Open the database, falling back beside the app if the profile is read-only."""
    path = Path(path).expanduser()
    db = Database(path)
    try:
        db.conn.execute("SELECT 1")
        return db, None
    except (sqlite3.OperationalError, OSError) as exc:
        db.close()
        if not allow_fallback:
            raise
        fallback = portable_data_dir() / "finboard.db"
        if fallback == path:
            raise
        log.warning("Cannot open %s (%s); falling back to %s", path, exc, fallback)
        db = Database(fallback)
        db.conn.execute("SELECT 1")
        return db, fallback


def _configure_logging() -> None:
    try:
        handler = logging.FileHandler(log_path(), encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _install_excepthook() -> None:
    def hook(exc_type, exc, tb) -> None:
        log.error("Unhandled exception", exc_info=(exc_type, exc, tb))
        if QApplication.instance() is not None:
            detail = "".join(traceback.format_exception_only(exc_type, exc)).strip()
            QMessageBox.critical(
                None,
                "FinBoard 遇到问题",
                f"{detail}\n\n详细信息已写入日志：\n{log_path()}",
            )

    sys.excepthook = hook


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FinBoard.FinanceDesktop.1"
        )
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging()
    _set_windows_app_id()

    app = QApplication(sys.argv[:1])
    install_localizer(app)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(f"{__app_name__} · {__app_name_cn__}")
    app.setOrganizationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))

    settings = QSettings("FinBoard", "FinBoard")
    # The command-line language is a one-launch override; do not persist it.
    initial_language = args.language or str(settings.value("language", "zh"))
    set_language(initial_language)
    apply_locale()
    if args.theme:
        settings.setValue("theme", args.theme)
    initial_theme = args.theme or str(settings.value("theme", "light"))
    apply_theme(app, initial_theme)
    app.setFont(QFont("Segoe UI" if is_english() else "Microsoft YaHei UI", 10))

    db_path = args.db or (demo_db_path() if (args.demo or args.reset_demo) else default_db_path())
    _install_excepthook()
    db, fallback = _open_database(Path(db_path), allow_fallback=args.db is None)
    repo = Repository(db)
    if args.reset_demo or (
        (args.demo or args.reset_demo) and repo.count_transactions(TransactionFilter(limit=1)) == 0
    ):
        repo.clear_all(seed_defaults=False)
        from .core.demo import seed_demo

        seed_demo(repo)

    service = FinanceService(repo, str(settings.value("currency", "CNY")))

    window = MainWindow(
        service, settings, language=initial_language, theme=initial_theme
    )
    window.show()
    if fallback is not None:
        window.notify(t("默认数据目录不可写，已改用 {path}", path=fallback.parent))
    if args.smoke_test:
        QTimer.singleShot(1200, app.quit)
    log.info(
        "Started %s %s with database %s", __app_name__, __version__, repo.db.path
    )

    def _shutdown() -> None:
        try:
            db.close()
        except Exception:
            pass

    app.aboutToQuit.connect(_shutdown)
    return app.exec()
