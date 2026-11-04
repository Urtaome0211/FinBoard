"""Fluent main window: FluentWindow navigation shell plus the FinBoard pages."""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    Theme,
    TransparentToolButton,
    setTheme,
    setThemeColor,
)

from ..core.dates import month_of, today
from ..core.models import Account, Transaction
from ..core.rates import RateSnapshot, RateStore
from ..i18n import is_english, language, set_language as set_ui_language, t
from .dialogs import AccountDialog, TransactionDialog
from .icons import app_icon
from .localize import apply_locale, localize_widgets
from .pages import (
    AccountsPage,
    BudgetsPage,
    DashboardPage,
    DebtsPage,
    FixedAssetsPage,
    ForecastPage,
    PlannedPage,
    ReceivablesPage,
    RecurringPage,
    ReportsPage,
    SavingsPage,
    SettingsPage,
    TransactionsPage,
)
from .theme import apply_theme, is_dark, theme_mode, theme_store

if TYPE_CHECKING:
    from ..core.service import FinanceService

NAV_ITEMS = [
    ("dashboard", "总览"),
    ("transactions", "收支明细"),
    ("accounts", "账户"),
    ("debts", "负债"),
    ("fixed_assets", "固定资产"),
    ("budgets", "预算"),
    ("savings", "储蓄"),
    ("planned", "计划"),
    ("receivables", "往来款"),
    ("forecast", "预测"),
    ("recurring", "定期"),
    ("reports", "报表"),
]

NAV_ICONS = {
    "dashboard": FluentIcon.HOME,
    "transactions": FluentIcon.DOCUMENT,
    "accounts": FluentIcon.FOLDER,
    "debts": FluentIcon.CERTIFICATE,
    "fixed_assets": FluentIcon.TILES,
    "budgets": FluentIcon.PIE_SINGLE,
    "savings": FluentIcon.LEAF,
    "planned": FluentIcon.CALENDAR,
    "receivables": FluentIcon.PEOPLE,
    "forecast": FluentIcon.MARKET,
    "recurring": FluentIcon.SYNC,
    "reports": FluentIcon.PIE_SINGLE,
}


class _RateFetchThread(QThread):
    """Network-only worker; SQLite writes happen back on the GUI thread."""

    fetched = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.fetched.emit(RateStore.fetch_latest())
        except Exception as exc:  # keep the UI alive offline
            self.failed.emit(str(exc))


class MainWindow(FluentWindow):
    def __init__(
        self,
        service: "FinanceService",
        settings: QSettings | None = None,
        *,
        language: str | None = None,
        theme: str | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.settings = settings or QSettings("FinBoard", "FinBoard")
        self.current_key = "dashboard"
        self._rate_thread: _RateFetchThread | None = None
        self._quitting = False
        self._tray: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_hint_shown = False

        set_ui_language(language or str(self.settings.value("language", "zh")))
        apply_locale()

        mode = theme or str(self.settings.value("theme", "light"))
        if mode not in ("light", "dark"):
            mode = "light"
        apply_theme(QApplication.instance(), mode)
        self._apply_fluent_theme(mode)

        self.setWindowTitle(t("FinBoard Fluent · 财观"))
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1100, 720)
        self.resize(1400, 880)
        use_mica = sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        self.setMicaEffectEnabled(use_mica)

        self.stack = self.stackedWidget
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self.service, self),
            "transactions": TransactionsPage(self.service, self),
            "accounts": AccountsPage(self.service, self),
            "debts": DebtsPage(self.service, self),
            "fixed_assets": FixedAssetsPage(self.service, self),
            "budgets": BudgetsPage(self.service, self),
            "savings": SavingsPage(self.service, self),
            "planned": PlannedPage(self.service, self),
            "receivables": ReceivablesPage(self.service, self),
            "forecast": ForecastPage(self.service, self),
            "recurring": RecurringPage(self.service, self),
            "reports": ReportsPage(self.service, self),
            "settings": SettingsPage(self.service, self),
        }
        for key, page in self.pages.items():
            page.setObjectName(f"page_{key}")

        self._build_navigation()
        self._build_titlebar_actions()
        self._build_shortcuts()
        self._build_tray()
        self._restore_geometry()
        self.refresh_all()
        localize_widgets(self)

        self.service.changed.connect(self._on_data_changed)
        theme_store.changed.connect(self._on_theme_changed)
        self._update_theme_button()
        self.navigate("dashboard")
        QTimer.singleShot(1200, self._auto_refresh_rates)
        QTimer.singleShot(1200, self._check_reminders)

    # ------------------------------------------------------------------ UI
    def _build_navigation(self) -> None:
        for key, text in NAV_ITEMS:
            self.addSubInterface(
                self.pages[key],
                NAV_ICONS[key],
                t(text),
                position=NavigationItemPosition.TOP,
            )
        self.addSubInterface(
            self.pages["settings"],
            FluentIcon.SETTING,
            t("设置"),
            position=NavigationItemPosition.BOTTOM,
        )
        self.navigationInterface.setExpandWidth(250)
        self.navigationInterface.setMinimumExpandWidth(900)
        self.navigationInterface.expand(useAni=False)
        self.stackedWidget.currentChanged.connect(self._on_page_changed)

    def _build_titlebar_actions(self) -> None:
        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText(t("搜索交易…"))
        self.search.setFixedWidth(220)
        self.search.setFixedHeight(32)
        self.search.returnPressed.connect(self._apply_global_search)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(260)
        self.search_timer.timeout.connect(self._apply_global_search)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())

        self.add_button = PrimaryPushButton(t("记一笔"), self)
        self.add_button.setFixedHeight(32)
        self.add_button.clicked.connect(lambda _checked=False: self.open_transaction())

        self.currency_chip = PushButton(self.service.currency, self)
        self.currency_chip.setFixedSize(64, 32)
        self.currency_chip.setToolTip(t("基准币种 · 打开汇率与货币设置"))
        self.currency_chip.clicked.connect(lambda: self.navigate("settings"))

        self.theme_button = TransparentToolButton(self)
        self.theme_button.setFixedSize(32, 32)
        self.theme_button.clicked.connect(self.toggle_theme)

        bar = self.titleBar.hBoxLayout
        bar.insertWidget(2, self.search)
        bar.insertWidget(3, self.add_button)
        bar.insertWidget(4, self.currency_chip)
        bar.insertWidget(5, self.theme_button)

    def _build_shortcuts(self) -> None:
        self._shortcuts = []
        bindings = [
            ("Ctrl+N", self.open_transaction),
            ("Ctrl+Shift+N", self.copy_last_transaction),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+Z", self.undo_last),
            ("Ctrl+,", lambda: self.navigate("settings")),
        ]
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        for index, (key, _text) in enumerate(NAV_ITEMS, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda k=key: self.navigate(k))
            self._shortcuts.append(shortcut)

    # ------------------------------------------------------------------ behavior
    def _on_page_changed(self, index: int) -> None:
        widget = self.stackedWidget.widget(index)
        if widget is None:
            return
        key = widget.objectName().removeprefix("page_")
        if key in self.pages:
            self.current_key = key

    def navigate(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.current_key = key
        self.navigationInterface.setCurrentItem(page.objectName())
        self.switchTo(page)
        if key == "transactions":
            page.reload()
        elif key != "settings" and hasattr(page, "refresh"):
            page.refresh()
        self.search_timer.stop()
        self._update_currency_chip()
        localize_widgets(self)

    def refresh_all(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()
        self._update_currency_chip()
        localize_widgets(self)

    def _on_data_changed(self) -> None:
        self.refresh_all()

    def _update_currency_chip(self) -> None:
        if hasattr(self, "currency_chip"):
            self.currency_chip.setText(self.service.currency)

    def _auto_refresh_rates(self) -> None:
        if self._quitting:
            return
        if not self.service.rate_store.should_refresh():
            return
        if self._rate_thread is not None and self._rate_thread.isRunning():
            return
        thread = _RateFetchThread(self)
        thread.fetched.connect(self._rates_fetched)
        thread.failed.connect(self._rates_failed)
        thread.finished.connect(self._rate_finished)
        self._rate_thread = thread
        thread.start()

    def _rates_fetched(self, snapshot: RateSnapshot) -> None:
        try:
            self.service.rate_store.save(snapshot)
        except Exception as exc:
            self.service.rate_store.mark_failed(str(exc))
            return
        self.service.changed.emit()

    def _rates_failed(self, message: str) -> None:
        try:
            self.service.rate_store.mark_failed(message)
        except Exception:
            pass
        settings = self.pages.get("settings")
        if settings is not None and hasattr(settings, "refresh"):
            settings.refresh()

    def _rate_finished(self) -> None:
        if self._rate_thread is not None:
            self._rate_thread.deleteLater()
            self._rate_thread = None

    # ------------------------------------------------------------------ dialogs
    def open_transaction(self, transaction: Transaction | None = None) -> None:
        dialog = TransactionDialog(self.service, transaction, parent=self)
        localize_widgets(dialog)
        dialog.exec()

    def copy_last_transaction(self) -> None:
        recent = self.service.repo.recent_transactions(1)
        if not recent:
            self.notify(t("还没有可复制的记录"))
            return
        dialog = TransactionDialog(self.service, duplicate=recent[0], parent=self)
        localize_widgets(dialog)
        dialog.exec()

    def open_account(self, account: Account | None = None) -> None:
        dialog = AccountDialog(self.service, account, parent=self)
        localize_widgets(dialog)
        dialog.exec()

    def refund_transaction(self, transaction: Transaction) -> None:
        dialog = TransactionDialog(
            self.service,
            parent=self,
            default_kind="income",
            refund_of=transaction,
        )
        localize_widgets(dialog)
        dialog.exec()

    # ------------------------------------------------------------------ tray
    def _build_tray(self) -> None:
        if not self.settings.value("tray/enabled", True, type=bool):
            return
        if self._tray is not None or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip(t("FinBoard Fluent — 个人财务"))
        menu = QMenu()
        menu.addAction(t("打开 FinBoard"), self._show_from_tray)
        menu.addAction(t("记一笔"), self._quick_add_from_tray)
        menu.addAction(t("复制上一笔"), self._quick_copy_from_tray)
        menu.addSeparator()
        menu.addAction(t("退出"), self._quit_from_tray)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._tray = tray
        self._tray_menu = menu

    def _tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quick_add_from_tray(self) -> None:
        self._show_from_tray()
        self.open_transaction()

    def _quick_copy_from_tray(self) -> None:
        self._show_from_tray()
        self.copy_last_transaction()

    def _quit_from_tray(self) -> None:
        self._quitting = True
        if self._tray is not None:
            self._tray.hide()
        QApplication.quit()

    def set_tray_enabled(self, enabled: bool) -> None:
        self.settings.setValue("tray/enabled", bool(enabled))
        self.settings.sync()
        if enabled:
            self._build_tray()
        elif self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
            self._tray_menu = None

    def _check_reminders(self) -> None:
        if not self.settings.value("reminders/enabled", True, type=bool):
            return
        messages: list[str] = []
        try:
            matured = self.service.matured_term_deposits()
            if matured:
                messages.append(
                    t("有 {count} 笔定期存款已到期，请确认支取。", count=len(matured))
                )
            month = month_of(today())
            lines = self.service.repo.budget_lines(month)
            overall = next((line for line in lines if line.is_overall), None)
            if overall is not None and overall.remaining < 0:
                messages.append(
                    t(
                        "本月预算已超支 {amount}",
                        amount=self.service.format(-overall.remaining),
                    )
                )
            due = self.service.repo.due_recurring()
            if due:
                messages.append(t("有 {count} 笔定期交易待确认入账", count=len(due)))
            for debt in self.service.repo.debts():
                if debt.is_credit:
                    cycle = self.service.repo.debt_credit_cycle(debt.account_id)
                    if cycle is not None and 0 <= cycle.days_until_due <= 3:
                        messages.append(
                            t(
                                "信用卡 {name} 将在 {days} 天后到期",
                                name=debt.account_name,
                                days=cycle.days_until_due,
                            )
                        )
                else:
                    schedule = self.service.repo.debt_schedule(debt.account_id)
                    if not schedule:
                        continue
                    try:
                        days = (date.fromisoformat(schedule[0].date) - date.today()).days
                    except ValueError:
                        continue
                    if 0 <= days <= 3:
                        messages.append(
                            t(
                                "贷款 {name} 将在 {days} 天后还款",
                                name=debt.account_name,
                                days=days,
                            )
                        )
        except Exception:
            return
        if not messages:
            return
        text = "\n".join(messages[:4])
        if self._tray is not None and self._tray.isVisible():
            self._tray.showMessage(
                t("FinBoard 提醒"),
                text,
                QSystemTrayIcon.MessageIcon.Information,
                9000,
            )
        else:
            self.notify(text)

    def undo_last(self) -> None:
        try:
            if not self.service.has_undo():
                self.notify(t("没有可撤销的操作"))
                return
            message = self.service.undo_last()
        except ValueError as exc:
            self.notify(str(exc))
            return
        self.notify(message)

    def notify(self, text: str) -> None:
        InfoBar.success(
            title=t("FinBoard"),
            content=t(text),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2600,
            parent=self,
        )

    # ------------------------------------------------------------------ language
    def set_language(self, code: str) -> "MainWindow":
        """Switch language by rebuilding the page tree.

        Translations are applied to Chinese source strings at widget
        construction time, so translating the existing English tree back to
        Chinese cannot recover the source text.  Rebuilding the window is the
        reliable path and also keeps dynamic labels (dates, counters) correct.
        """
        if code not in ("zh", "en") or code == language():
            return self
        self.settings.setValue("language", code)
        set_ui_language(code)
        apply_locale()
        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont("Segoe UI" if is_english() else "Microsoft YaHei UI", 10))

        current = self.current_key
        geometry = self.saveGeometry()
        maximized = self.isMaximized()
        replacement = MainWindow(
            self.service,
            self.settings,
            language=code,
            theme=theme_mode(),
        )
        replacement.restoreGeometry(geometry)
        if maximized:
            replacement.showMaximized()
        else:
            replacement.show()
        replacement.navigate(current)
        replacement.raise_()
        replacement.activateWindow()

        # Stop the background rate fetch before tearing this shell down;
        # deleting a QThread while it is still running crashes Qt.
        if self._rate_thread is not None:
            if self._rate_thread.isRunning():
                self._rate_thread.wait(10_000)
            self._rate_thread.deleteLater()
            self._rate_thread = None

        # Close the old shell after the replacement is visible.  ``hide()``
        # first prevents the tray-enabled closeEvent from leaving a ghost.
        self._quitting = True
        self.hide()
        self.close()
        self.deleteLater()
        return replacement

    # ------------------------------------------------------------------ theme
    def toggle_theme(self) -> None:
        self.set_theme("light" if is_dark() else "dark")

    def set_theme(self, mode: str) -> None:
        if mode not in ("light", "dark") or mode == theme_mode():
            return
        self.settings.setValue("theme", mode)
        apply_theme(QApplication.instance(), mode)
        self._apply_fluent_theme(mode)
        self._update_theme_button()

    def _apply_fluent_theme(self, mode: str) -> None:
        setTheme(Theme.DARK if mode == "dark" else Theme.LIGHT)
        setThemeColor("#3D6DF2")

    def _on_theme_changed(self) -> None:
        self._update_theme_button()
        self.refresh_all()

    def _update_theme_button(self) -> None:
        if not hasattr(self, "theme_button"):
            return
        self.theme_button.setIcon(FluentIcon.BRIGHTNESS)
        self.theme_button.setToolTip(t("切换浅色 / 深色主题"))

    def set_currency(self, code: str) -> None:
        self.service.set_currency(code)
        self.settings.setValue("currency", code)
        self._update_currency_chip()
        self.refresh_all()
        self.notify(t("货币已切换为 {code}", code=code))

    # ------------------------------------------------------------------ search
    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _apply_global_search(self) -> None:
        text = self.search.text().strip()
        if not text:
            return
        page = self.pages["transactions"]
        if self.current_key != "transactions":
            self.navigate("transactions")
        page.search_everything(text)

    # ------------------------------------------------------------------ window
    def _restore_geometry(self) -> None:
        raw = self.settings.value("geometry")
        if raw:
            self.restoreGeometry(raw)
        else:
            screen = QApplication.primaryScreen()
            if screen is not None:
                frame = self.frameGeometry()
                frame.moveCenter(screen.availableGeometry().center())
                self.move(frame.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.settings.setValue("geometry", self.saveGeometry())
        if (
            not self._quitting
            and self._tray is not None
            and self._tray.isVisible()
            and self.settings.value("tray/enabled", True, type=bool)
        ):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._tray.showMessage(
                    t("FinBoard 仍在后台运行"),
                    t("托盘图标可随时打开窗口或退出。"),
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            return
        if self._rate_thread is not None and self._rate_thread.isRunning():
            self._rate_thread.wait(10_000)
        super().closeEvent(event)
