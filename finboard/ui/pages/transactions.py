"""Searchable ledger of every income, expense and transfer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.models import TransactionFilter
from ...i18n import category_display, t
from ..dialogs import MetadataDialog
from ..models import KindBadgeDelegate, TransactionTableModel
from ..widgets import (
    Card,
    ComboBox,
    EmptyState,
    MonthCombo,
    Page,
    PageHeader,
    SearchInput,
    SegmentedControl,
    ThemedButton,
    ConfirmDialog,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class TransactionsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window
        self._loading = False

        header = PageHeader("收支明细", "")
        export_button = ThemedButton(t("导出 CSV"), "secondary", "download")
        export_button.clicked.connect(self._export)
        record_button = ThemedButton(t("记一笔"), "primary", "plus")
        record_button.clicked.connect(lambda: self.window.open_transaction())
        header.add_action(export_button)
        header.add_action(record_button)
        self.header = header
        self.body.addWidget(header)

        filter_card = Card(padding=14, spacing=10)
        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search = SearchInput(t("搜索对方或备注…"))
        self.search.setMinimumWidth(190)
        filters.addWidget(self.search, 1)

        self.month_combo = MonthCombo(include_all=True)
        filters.addWidget(self.month_combo)

        self.kind_control = SegmentedControl(
            [
                (t("全部"), None),
                (t("支出"), "expense"),
                (t("收入"), "income"),
                (t("转账"), "transfer"),
            ],
            None,
        )
        filters.addWidget(self.kind_control)

        self.account_combo = ComboBox()
        self.account_combo.setMinimumWidth(140)
        self.account_combo.setProperty("i18nSkip", True)
        filters.addWidget(self.account_combo)

        self.category_combo = ComboBox()
        self.category_combo.setMinimumWidth(120)
        filters.addWidget(self.category_combo)

        self.reset_button = ThemedButton(t("重置"), "ghost", "refresh")
        self.reset_button.clicked.connect(self._reset_filters)
        filters.addWidget(self.reset_button)
        filter_card.body.addLayout(filters)
        self.body.addWidget(filter_card)

        self.stack = QStackedWidget()
        self.table_card = Card(padding=0, spacing=0)
        self.table = QTableView()
        self.model = TransactionTableModel(service)
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(1, KindBadgeDelegate(self.table))
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.setAlternatingRowColors(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._open_index)
        header_view = self.table.horizontalHeader()
        header_view.setHighlightSections(False)
        header_view.setStretchLastSection(False)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 104)
        self.table.setColumnWidth(1, 96)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 210)
        self.table.setColumnWidth(5, 148)
        self.table.setColumnWidth(6, 118)
        self.table.setColumnWidth(7, 70)

        self.empty = EmptyState(
            "list",
            t("没有找到记录"),
            t("换一个筛选条件，或先记一笔。"),
            t("记一笔"),
            lambda: self.window.open_transaction(),
        )
        table_wrap = QWidget()
        table_layout = QVBoxLayout(table_wrap)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table)
        self.table_card.body.addWidget(table_wrap)
        self.stack.addWidget(self.table_card)
        self.stack.addWidget(self.empty)
        self.body.addWidget(self.stack, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(4, 0, 4, 2)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        footer_layout.addWidget(self.summary)
        footer_layout.addStretch(1)
        self.hint = QLabel(t("双击编辑 · 右键删除"))
        self.hint.setProperty("role", "faint")
        footer_layout.addWidget(self.hint)
        self.body.addWidget(footer)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(260)
        self.search_timer.timeout.connect(self.reload)

        self._load_filter_options()
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        self.month_combo.currentIndexChanged.connect(lambda _index: self.reload())
        self.kind_control.changed.connect(self._kind_changed)
        self.account_combo.currentIndexChanged.connect(lambda _index: self.reload())
        self.category_combo.currentIndexChanged.connect(lambda _index: self.reload())

        self.delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.table)
        self.delete_shortcut.activated.connect(self._delete_current)

    # ------------------------------------------------------------------
    def _load_filter_options(self) -> None:
        self._loading = True
        account_id = self.account_combo.currentData()
        category_id = self.category_combo.currentData()
        self.account_combo.clear()
        self.account_combo.addItem(t("全部账户"), None)
        for account in self.service.repo.accounts(include_archived=True):
            suffix = t("（已归档）") if account.archived else ""
            self.account_combo.addItem(account.name + suffix, account.id)
        if account_id is not None:
            index = self.account_combo.findData(account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self._load_categories(category_id)
        self._loading = False

    def _load_categories(self, selected: int | None = None) -> None:
        kind = self.kind_control.value() if hasattr(self, "kind_control") else None
        category_id = selected
        if category_id is None and hasattr(self, "category_combo"):
            category_id = self.category_combo.currentData()
        self.category_combo.clear()
        self.category_combo.addItem(t("全部分类"), None)
        if kind == "transfer":
            self.category_combo.setEnabled(False)
            return
        self.category_combo.setEnabled(True)
        kinds = [kind] if kind in ("expense", "income") else ["expense", "income"]
        for category_kind in kinds:
            for category in self.service.repo.categories(category_kind):
                label = category_display(category.name)
                if len(kinds) > 1:
                    label += f" · {t(category.kind_label)}"
                self.category_combo.addItem(label, category.id)
        if category_id is not None:
            index = self.category_combo.findData(category_id)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _kind_changed(self, kind: str | None) -> None:
        if self._loading:
            return
        self._load_categories()
        self.reload()

    def _reset_filters(self) -> None:
        self._loading = True
        self.search.clear()
        self.kind_control.set_value(None)
        self.month_combo.setCurrentIndex(0)
        self.account_combo.setCurrentIndex(0)
        self._load_categories()
        self._loading = False
        self.reload()

    # ------------------------------------------------------------------
    def filters(self, *, limit: int = 500) -> TransactionFilter:
        return TransactionFilter(
            month=self.month_combo.current_month(),
            kind=self.kind_control.value(),  # type: ignore[arg-type]
            category_id=self.category_combo.currentData(),
            account_id=self.account_combo.currentData(),
            search=self.search.text().strip(),
            limit=limit,
        )

    def reload(self) -> None:
        if self._loading:
            return
        filters = self.filters()
        rows = self.service.repo.transactions(filters)
        balances = self.service.transaction_balances([row.id for row in rows])
        self.model.set_transactions(rows, balances)
        count = self.service.repo.count_transactions(filters)
        self.header.set_subtitle(t("共 {count} 笔记录", count=count))
        if rows:
            self.stack.setCurrentWidget(self.table_card)
        else:
            self.stack.setCurrentWidget(self.empty)
        try:
            income = sum(
                self.service.to_base(row.amount, row.currency, row.date)
                for row in rows
                if row.kind == "income"
            )
            expense = sum(
                self.service.to_base(row.amount, row.currency, row.date)
                for row in rows
                if row.kind == "expense"
            )
            expense += sum(
                self.service.to_base(row.fee, row.account_currency, row.date)
                for row in rows
                if row.kind == "transfer" and row.fee
            )
        except ValueError:
            self.summary.setText(
                t("当前 {count} 笔 · 汇率不足，无法汇总", count=len(rows))
            )
            return
        text = t(
            "当前 {count} 笔 · 收入 {income} · 支出 {expense}",
            count=len(rows),
            income=self.service.format(income),
            expense=self.service.format(expense),
        )
        if count > len(rows):
            text += t(" · 仅显示最新 {count} 笔", count=len(rows))
        self.summary.setText(text)

    def refresh(self) -> None:
        self._load_filter_options()
        self.reload()

    def set_search(self, text: str) -> None:
        self.search.setText(text)
        self.search_timer.stop()
        self.reload()

    def search_everything(self, text: str) -> None:
        """Clear filters so a global search covers the whole ledger."""
        self._loading = True
        self.month_combo.setCurrentIndex(0)
        self.kind_control.set_value(None)
        self.account_combo.setCurrentIndex(0)
        self._load_categories(None)
        self._loading = False
        self.set_search(text)

    def focus_search(self) -> None:
        self.search.setFocus()

    # ------------------------------------------------------------------
    def _open_index(self, index) -> None:
        if not index.isValid():
            return
        transaction = self.model.transaction_at(index.row())
        if transaction:
            self.window.open_transaction(transaction)

    def _context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        transaction = self.model.transaction_at(index.row())
        if not transaction:
            return
        menu = QMenu(self)
        edit = QAction(t("编辑记录"), menu)
        edit.triggered.connect(lambda: self.window.open_transaction(transaction))
        metadata = QAction(t("标签、拆分与附件…"), menu)
        metadata.triggered.connect(lambda: self._open_metadata(transaction))
        remove = QAction(t("删除记录"), menu)
        remove.triggered.connect(lambda: self._delete(transaction))
        menu.addAction(edit)
        menu.addAction(metadata)
        menu.addSeparator()
        menu.addAction(remove)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _open_metadata(self, transaction) -> None:
        MetadataDialog(self.service, transaction, self).exec()
        self.reload()

    def _delete_current(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        transaction = self.model.transaction_at(index.row())
        if transaction:
            self._delete(transaction)

    def _delete(self, transaction) -> None:
        if not ConfirmDialog.confirm(
            self,
            t("删除这笔记录？"),
            t(
                "{date} · {title}\n{amount}，删除后账户余额会同步调整。",
                date=transaction.date,
                title=transaction.title,
                amount=self.service.format(transaction.amount),
            ),
            ok_text=t("删除"),
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            self.service.delete_transaction(transaction.id)
        except ValueError as exc:
            ConfirmDialog.alert(self, "删除失败", str(exc), icon_name="alert")

    def _export(self) -> None:
        month = self.month_combo.current_month() or t("全部")
        default = Path.home() / "Desktop" / f"FinBoard-收入支出-{month}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, t("导出收支明细"), str(default), t("CSV 文件 (*.csv)")
        )
        if not path:
            return
        try:
            count = self.service.export_csv(path, self.filters(limit=100_000))
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, t("导出失败"), str(exc), icon_name="alert")
            return
        self.window.notify(
            t("已导出 {count} 笔记录到 {name}", count=count, name=Path(path).name)
        )
