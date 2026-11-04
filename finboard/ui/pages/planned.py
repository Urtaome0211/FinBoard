"""Planned one-off income, expense and transfers."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import PlannedTransaction
from ...core.service import FinanceService
from ...i18n import t
from ..dialogs import PlannedDialog
from ..theme import colors
from ..widgets import (
    Badge,
    Card,
    ConfirmDialog,
    EmptyState,
    IconButton,
    Page,
    PageHeader,
    ThemedButton,
    clear_layout,
    divider,
    icon_label,
)
from .components import StatCard


class PlannedRow(QFrame):
    confirm_requested = Signal(int)
    cancel_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(
        self,
        item: PlannedTransaction,
        service: FinanceService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("ListRow")
        self.setMinimumHeight(80)
        palette = colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 6, 4, 6)
        row.setSpacing(14)
        row.addWidget(
            icon_label(
                "calendar",
                palette.primary,
                18,
                palette.primary_soft,
                box=36,
                radius=10,
            )
        )
        column = QVBoxLayout()
        column.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(item.title)
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        top.addWidget(title)
        if item.status == "done":
            top.addWidget(Badge(t("已入账"), "income"))
        elif item.status == "cancelled":
            top.addWidget(Badge(t("已取消"), "neutral"))
        else:
            top.addWidget(Badge(t("待确认"), "primary"))
        top.addStretch(1)
        column.addLayout(top)
        meta = QLabel(
            t("{date} · {account}").format(
                date=item.date,
                account=item.account_name or "—",
            )
        )
        meta.setProperty("role", "muted")
        column.addWidget(meta)
        row.addLayout(column, 1)

        if item.kind == "transfer":
            amount_text = "→ " + service.format(item.amount)
        else:
            amount_text = service.format(item.signed_amount, plus=item.kind == "income")
        amount = QLabel(amount_text)
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount.setStyleSheet("font-size: 15px; font-weight: 700;")
        amount.setProperty(
            "role",
            "income" if item.kind == "income" else "expense" if item.kind == "expense" else "muted",
        )
        row.addWidget(amount)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        if item.is_open:
            confirm = ThemedButton(t("确认入账"), "secondary")
            confirm.clicked.connect(lambda: self.confirm_requested.emit(item.id))
            actions.addWidget(confirm)
            skip = ThemedButton(t("取消"), "ghost")
            skip.clicked.connect(lambda: self.cancel_requested.emit(item.id))
            actions.addWidget(skip)
        delete = IconButton("trash", t("删除计划"), size=16)
        delete.clicked.connect(lambda: self.delete_requested.emit(item.id))
        actions.addWidget(delete)
        row.addLayout(actions)


class PlannedPage(Page):
    def __init__(self, service: FinanceService, window: QWidget) -> None:
        super().__init__()
        self.service = service
        self.window = window
        header = PageHeader(
            t("计划"),
            t("一次性的大额收支，提前放进现金流，确认后才真正入账"),
        )
        add = ThemedButton(t("新建计划"), "primary", "plus")
        add.clicked.connect(self._add)
        header.add_action(add)
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.income_card = StatCard(t("未来收入"), "trending-up", tone="income")
        self.expense_card = StatCard(t("未来支出"), "trending-down", tone="expense")
        self.net_card = StatCard(t("未来净额"), "savings", tone="primary")
        self.count_card = StatCard(t("待确认"), "clock", tone="accent")
        for card in (
            self.income_card,
            self.expense_card,
            self.net_card,
            self.count_card,
        ):
            stats.addWidget(card)
        self.body.addLayout(stats)

        self.card = Card()
        head = QHBoxLayout()
        title = QLabel(t("计划列表"))
        title.setProperty("role", "sectionTitle")
        head.addWidget(title)
        self.hint = QLabel()
        self.hint.setProperty("role", "faint")
        head.addWidget(self.hint)
        head.addStretch(1)
        self.card.body.addLayout(head)
        self.card.body.addWidget(divider())
        self.rows = QVBoxLayout()
        self.rows.setSpacing(0)
        self.card.body.addLayout(self.rows)
        self.body.addWidget(self.card)

        self.empty = EmptyState(
            "calendar",
            t("还没有计划"),
            t("把首付、学费或年终奖写进来，预测会把它算进去"),
            t("新建计划"),
            self._add,
        )
        self.body.addWidget(self.empty)
        self.body.addStretch(1)
        self.refresh()

    def _add(self) -> None:
        PlannedDialog(self.service, parent=self.window).exec()

    def _base(self, amount: int, currency: str, day: str) -> int:
        try:
            return self.service.to_base(amount, currency, day)
        except Exception:
            return amount

    def _confirm(self, planned_id: int) -> None:
        try:
            self.service.confirm_planned_transaction(planned_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("无法确认计划"), str(exc))
            return
        self.refresh()

    def _cancel(self, planned_id: int) -> None:
        try:
            self.service.cancel_planned_transaction(planned_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("无法取消计划"), str(exc))
            return
        self.refresh()

    def _delete(self, planned_id: int) -> None:
        if not ConfirmDialog.confirm(
            self.window,
            t("删除计划？"),
            t("删除后不会再出现在预测中，已入账的交易不受影响。"),
            ok_text=t("删除"),
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            self.service.delete_planned_transaction(planned_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("删除失败"), str(exc))
            return
        self.refresh()

    def refresh(self) -> None:
        items = self.service.repo.planned_transactions()
        open_items = [item for item in items if item.is_open]
        income = sum(
            self._base(item.amount, item.currency, item.date)
            for item in open_items
            if item.kind == "income"
        )
        expense = sum(
            self._base(item.amount, item.currency, item.date)
            for item in open_items
            if item.kind == "expense"
        )
        self.income_card.set_value(self.service.format(income))
        self.expense_card.set_value(self.service.format(expense))
        self.net_card.set_value(self.service.format(income - expense, plus=True))
        self.count_card.set_value(str(len(open_items)), hint=t("确认后自动入账"))

        clear_layout(self.rows)
        for item in items:
            row = PlannedRow(item, self.service)
            row.confirm_requested.connect(self._confirm)
            row.cancel_requested.connect(self._cancel)
            row.delete_requested.connect(self._delete)
            self.rows.addWidget(row)
        self.card.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.hint.setText(t("{count} 笔计划").format(count=len(items)) if items else "")
