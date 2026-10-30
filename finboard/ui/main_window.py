"""Main application window: sidebar, top bar and page stack."""

from __future__ import annotations

import ctypes
import sys
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.dates import full_date_label, month_of, today
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
    RecurringPage,
    ReportsPage,
    SettingsPage,
    TransactionsPage,
)
from .theme import apply_theme, colors, is_dark, theme_mode, theme_store
from .widgets import (
    IconButton,
    NavButton,
    SearchInput,
    ThemedButton,
    ValueLabel,
)

if TYPE_CHECKING:
    from ..core.service import FinanceService

NAV_ITEMS = [
    ("dashboard", "dashboard", "总览"),
    ("transactions", "list", "收支明细"),
    ("accounts", "wallet", "账户"),
    ("budgets", "target", "预算"),
    ("recurring", "calendar", "定期"),
    ("reports", "chart", "报表"),
]


class _RateFetchThread(QThread):
    """Network-only worker; SQLite writes happen back on the GUI thread."""

    fetched = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.fetched.emit(RateStore.fetch_latest())
        except Exception as exc:  # keep the UI alive offline
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
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
        set_ui_language(language or str(self.settings.value("language", "zh")))
        apply_locale()

        mode = theme or str(self.settings.value("theme", "light"))
        if mode not in ("light", "dark"):
            mode = "light"
        apply_theme(QApplication.instance(), mode)

        self.setWindowTitle(t("FinBoard · 财观 — 个人财务管理"))
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1100, 720)
        self.resize(1400, 880)

        self._build_ui()
        self._build_shortcuts()
        self._restore_geometry()
        self._update_greeting()
        self._update_currency_chip()
        self._update_sidebar_balance()
        self.refresh_all()
        localize_widgets(self)

        self.service.changed.connect(self._on_data_changed)
        theme_store.changed.connect(self._on_theme_changed)
        self._update_theme_button()
        QTimer.singleShot(0, self._apply_titlebar)
        QTimer.singleShot(1200, self._auto_refresh_rates)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        shell.addWidget(self._build_sidebar())

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self.service, self),
            "transactions": TransactionsPage(self.service, self),
            "accounts": AccountsPage(self.service, self),
            "budgets": BudgetsPage(self.service, self),
            "recurring": RecurringPage(self.service, self),
            "reports": ReportsPage(self.service, self),
            "settings": SettingsPage(self.service, self),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        column.addWidget(self.stack, 1)
        shell.addWidget(content, 1)

        self.toast = QLabel(root)
        self.toast.setObjectName("Toast")
        self.toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.toast.setMinimumWidth(120)
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._style_toast()
        self.toast.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast.hide)

        self.navigate("dashboard")

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(36, 36))
        logo.setFixedSize(36, 36)
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("FinBoard")
        title.setProperty("role", "brandTitle")
        subtitle = QLabel("财观 · 个人财务")
        subtitle.setProperty("role", "brandSubtitle")
        names.addWidget(title)
        names.addWidget(subtitle)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(22)

        section = QLabel("工作台")
        section.setProperty("role", "navSection")
        layout.addWidget(section)
        layout.addSpacing(4)

        self.nav_buttons: dict[str, NavButton] = {}
        for key, icon_name, text in NAV_ITEMS:
            button = NavButton(icon_name, text)
            button.clicked.connect(lambda _checked=False, k=key: self.navigate(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button

        layout.addStretch(1)

        balance = QFrame()
        balance.setObjectName("SoftCard")
        balance_layout = QVBoxLayout(balance)
        balance_layout.setContentsMargins(14, 12, 14, 12)
        balance_layout.setSpacing(3)
        caption = QLabel("本月结余")
        caption.setProperty("role", "muted")
        balance_layout.addWidget(caption)
        self.sidebar_balance = ValueLabel("¥0.00", size=19, weight=700)
        balance_layout.addWidget(self.sidebar_balance)
        self.sidebar_hint = QLabel("净资产 ¥0.00")
        self.sidebar_hint.setProperty("role", "faint")
        balance_layout.addWidget(self.sidebar_hint)
        layout.addWidget(balance)
        layout.addSpacing(10)

        settings_button = NavButton("settings", "设置")
        settings_button.clicked.connect(lambda _checked=False: self.navigate("settings"))
        layout.addWidget(settings_button)
        self.nav_buttons["settings"] = settings_button
        return sidebar

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Topbar")
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(28, 0, 24, 0)
        layout.setSpacing(12)

        greeting = QVBoxLayout()
        greeting.setSpacing(0)
        self.greeting_label = QLabel("你好")
        self.greeting_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.date_label = QLabel()
        self.date_label.setProperty("role", "faint")
        greeting.addWidget(self.greeting_label)
        greeting.addWidget(self.date_label)
        layout.addLayout(greeting)
        layout.addStretch(1)

        self.search = SearchInput()
        self.search.setPlaceholderText("搜索交易…")
        self.search.setFixedWidth(230)
        self.search.setFixedHeight(36)
        self.search.returnPressed.connect(self._apply_global_search)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(260)
        self.search_timer.timeout.connect(self._apply_global_search)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        layout.addWidget(self.search)

        self.currency_chip = ThemedButton("CNY", "ghost")
        self.currency_chip.setFixedSize(62, 38)
        self.currency_chip.setToolTip("基准币种 · 打开汇率与货币设置")
        self.currency_chip.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(self.currency_chip)

        add = ThemedButton("记一笔", "primary", "plus")
        add.setFixedHeight(38)
        add.clicked.connect(lambda _checked=False: self.open_transaction())
        layout.addWidget(add)

        self.theme_button = IconButton("moon", "切换浅色 / 深色主题", size=18)
        self.theme_button.setFixedSize(38, 38)
        self.theme_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.theme_button)
        return bar

    def _build_shortcuts(self) -> None:
        self._shortcuts = []
        bindings = [
            ("Ctrl+N", self.open_transaction),
            ("Ctrl+F", self._focus_search),
            ("Ctrl+,", lambda: self.navigate("settings")),
        ]
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        for index, key in enumerate([item[0] for item in NAV_ITEMS], start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda k=key: self.navigate(k))
            self._shortcuts.append(shortcut)

    # ------------------------------------------------------------------ behavior
    def navigate(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.current_key = key
        self.stack.setCurrentWidget(page)
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        if key == "transactions":
            page.reload()
        elif key != "settings" and hasattr(page, "refresh"):
            page.refresh()
        self.search_timer.stop()
        self._position_toast()
        localize_widgets(self)

    def refresh_all(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()
        self._update_currency_chip()
        self._update_sidebar_balance()
        localize_widgets(self)

    def _on_data_changed(self) -> None:
        self.refresh_all()

    def _update_currency_chip(self) -> None:
        if hasattr(self, "currency_chip"):
            self.currency_chip.setText(self.service.currency)

    def _auto_refresh_rates(self) -> None:
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

    def _update_sidebar_balance(self) -> None:
        month = month_of(today())
        stats = self.service.repo.month_stats(month)
        worth = self.service.repo.net_worth()
        self.sidebar_balance.setText(self.service.format(stats.net))
        self.sidebar_balance.set_tone(
            "income" if stats.net > 0 else ("expense" if stats.net < 0 else "text")
        )
        self.sidebar_hint.setText(t("净资产 {amount}", amount=self.service.format(worth.net)))

    def _update_greeting(self) -> None:
        hour = datetime.now().hour
        if hour < 6:
            phrase = t("夜深了")
        elif hour < 12:
            phrase = t("早上好")
        elif hour < 14:
            phrase = t("中午好")
        elif hour < 18:
            phrase = t("下午好")
        else:
            phrase = t("晚上好")
        self.greeting_label.setText(phrase)
        self.date_label.setText(full_date_label(today()))

    # ------------------------------------------------------------------ dialogs
    def open_transaction(self, transaction: Transaction | None = None) -> None:
        dialog = TransactionDialog(self.service, transaction, parent=self)
        localize_widgets(dialog)
        dialog.exec()

    def open_account(self, account: Account | None = None) -> None:
        dialog = AccountDialog(self.service, account, parent=self)
        localize_widgets(dialog)
        dialog.exec()

    def notify(self, text: str) -> None:
        self.toast.setText(t(text))
        self.toast.adjustSize()
        self.toast.setFixedHeight(max(36, self.toast.sizeHint().height()))
        self.toast.show()
        self.toast.raise_()
        self._position_toast()
        self.toast_timer.start(2600)

    def _position_toast(self) -> None:
        if not hasattr(self, "toast") or not self.toast.isVisible():
            return
        parent = self.toast.parentWidget()
        if parent is None:
            return
        x = max(12, parent.width() - self.toast.width() - 28)
        y = max(12, parent.height() - self.toast.height() - 22)
        self.toast.move(x, y)

    # ------------------------------------------------------------------ language
    def set_language(self, code: str) -> None:
        """Switch UI language and rebuild the window in place."""
        if code not in ("zh", "en") or code == language():
            return
        self.settings.setValue("language", code)
        set_ui_language(code)
        apply_locale()
        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont("Segoe UI" if is_english() else "Microsoft YaHei UI", 10))
        QTimer.singleShot(0, self._rebuild_for_language)

    def _rebuild_for_language(self) -> None:
        key = self.current_key
        self.toast_timer.stop()
        self.setWindowTitle(t("FinBoard · 财观 — 个人财务管理"))
        old = self.takeCentralWidget()
        if old is not None:
            old.deleteLater()
        self.pages.clear()
        self.nav_buttons.clear()
        self._build_ui()
        self.navigate(key)
        self._update_greeting()
        self._update_currency_chip()
        self._update_sidebar_balance()
        self._update_theme_button()
        self._apply_titlebar()
        localize_widgets(self)

    # ------------------------------------------------------------------ theme
    def toggle_theme(self) -> None:
        self.set_theme("light" if is_dark() else "dark")

    def set_theme(self, mode: str) -> None:
        if mode not in ("light", "dark") or mode == theme_mode():
            return
        self.settings.setValue("theme", mode)
        apply_theme(QApplication.instance(), mode)

    def _on_theme_changed(self) -> None:
        self._update_theme_button()
        self._apply_titlebar()
        self._style_toast()
        self.refresh_all()

    def _update_theme_button(self) -> None:
        if not hasattr(self, "theme_button"):
            return
        self.theme_button.set_icon_name("sun" if is_dark() else "moon")
        self.theme_button.setToolTip(t("切换浅色 / 深色主题"))

    def _style_toast(self) -> None:
        if not hasattr(self, "toast"):
            return
        palette = colors()
        self.toast.setStyleSheet(
            f"QLabel#Toast {{ background: {palette.text}; color: {palette.surface};"
            " border-radius: 10px; padding: 9px 16px; font-size: 12px; }"
        )

    def _apply_titlebar(self) -> None:
        if sys.platform != "win32" or not self.isVisible():
            return
        try:
            value = ctypes.c_int(1 if is_dark() else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()), 20, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass

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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_toast()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_titlebar)
        QTimer.singleShot(0, self._position_toast)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.settings.setValue("geometry", self.saveGeometry())
        if self._rate_thread is not None and self._rate_thread.isRunning():
            self._rate_thread.wait(10_000)
        super().closeEvent(event)
