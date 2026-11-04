"""Money owed to or by the user."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import Receivable
from ...core.service import FinanceService
from ...i18n import t
from ..dialogs import ReceivableDialog
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


class ReceivableRow(QFrame):
    settle_requested = Signal(int)
    reopen_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(
        self,
        item: Receivable,
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
                "transfer",
                palette.income if item.is_receivable else palette.expense,
                18,
                palette.income_soft if item.is_receivable else palette.expense_soft,
                box=36,
                radius=10,
            )
        )
        column = QVBoxLayout()
        column.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(item.counterparty)
        name.setProperty("i18nSkip", True)
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        top.addWidget(name)
        top.addWidget(
            Badge(t("应收") if item.is_receivable else t("应付"), "income" if item.is_receivable else "expense")
        )
        if item.is_open:
            if item.days_left is not None and item.days_left < 0:
                top.addWidget(Badge(t("已逾期"), "warning"))
            else:
                top.addWidget(Badge(t("未结清"), "neutral"))
        else:
            top.addWidget(Badge(t("已结清"), "neutral"))
        top.addStretch(1)
        column.addLayout(top)
        due = t("到期 {date}", date=item.due_date) if item.due_date else t("未设到期日")
        meta = QLabel(
            t("{date} · {due}{account}").format(
                date=item.date,
                due=due,
                account=f" · {item.account_name}" if item.account_name else "",
            )
        )
        meta.setProperty("role", "muted")
        column.addWidget(meta)
        row.addLayout(column, 1)

        amount = QLabel(
            service.format(item.signed_amount, plus=item.is_receivable)
        )
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount.setStyleSheet("font-size: 15px; font-weight: 700;")
        amount.setProperty("role", "income" if item.is_receivable else "expense")
        row.addWidget(amount)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        if item.is_open:
            action = ThemedButton(t("标记结清"), "secondary")
            action.clicked.connect(lambda: self.settle_requested.emit(item.id))
        else:
            action = ThemedButton(t("重新打开"), "ghost")
            action.clicked.connect(lambda: self.reopen_requested.emit(item.id))
        actions.addWidget(action)
        delete = IconButton("trash", t("删除往来款"), size=16)
        delete.clicked.connect(lambda: self.delete_requested.emit(item.id))
        actions.addWidget(delete)
        row.addLayout(actions)


class ReceivablesPage(Page):
    def __init__(self, service: FinanceService, window: QWidget) -> None:
        super().__init__()
        self.service = service
        self.window = window
        header = PageHeader(
            t("往来款"),
            t("借出、垫付、代收代付单独管理，结清不产生收支"),
        )
        add = ThemedButton(t("记一笔往来"), "primary", "plus")
        add.clicked.connect(self._add)
        header.add_action(add)
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.receivable_card = StatCard(t("应收"), "trending-up", tone="income")
        self.payable_card = StatCard(t("应付"), "trending-down", tone="expense")
        self.net_card = StatCard(t("净往来"), "transfer", tone="primary")
        self.overdue_card = StatCard(t("已逾期"), "clock", tone="accent")
        for card in (
            self.receivable_card,
            self.payable_card,
            self.net_card,
            self.overdue_card,
        ):
            stats.addWidget(card)
        self.body.addLayout(stats)

        self.card = Card()
        head = QHBoxLayout()
        title = QLabel(t("往来记录"))
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
            "transfer",
            t("还没有往来款"),
            t("朋友借钱、公司垫付报销，都可以记在这里"),
            t("记一笔往来"),
            self._add,
        )
        self.body.addWidget(self.empty)
        self.body.addStretch(1)
        self.refresh()

    def _add(self) -> None:
        ReceivableDialog(self.service, parent=self.window).exec()

    def _settle(self, item_id: int) -> None:
        try:
            self.service.settle_receivable(item_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("无法结清"), str(exc))
            return
        self.refresh()

    def _reopen(self, item_id: int) -> None:
        try:
            self.service.reopen_receivable(item_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("无法重新打开"), str(exc))
            return
        self.refresh()

    def _delete(self, item_id: int) -> None:
        if not ConfirmDialog.confirm(
            self.window,
            t("删除往来款？"),
            t("删除后无法恢复，但不会影响任何收支记录。"),
            ok_text=t("删除"),
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            self.service.delete_receivable(item_id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("删除失败"), str(exc))
            return
        self.refresh()

    def refresh(self) -> None:
        items = self.service.repo.receivables()
        totals = self.service.repo.receivables_totals()
        overdue = sum(
            1
            for item in items
            if item.is_open
            and item.days_left is not None
            and item.days_left < 0
        )
        self.receivable_card.set_value(self.service.format(totals.get("receivable", 0)))
        self.payable_card.set_value(self.service.format(totals.get("payable", 0)))
        self.net_card.set_value(
            self.service.format(
                totals.get("receivable", 0) - totals.get("payable", 0), plus=True
            )
        )
        self.overdue_card.set_value(str(overdue), hint=t("未结清的往来款"))

        clear_layout(self.rows)
        for item in items:
            row = ReceivableRow(item, self.service)
            row.settle_requested.connect(self._settle)
            row.reopen_requested.connect(self._reopen)
            row.delete_requested.connect(self._delete)
            self.rows.addWidget(row)
        self.card.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.hint.setText(t("{count} 笔记录").format(count=len(items)) if items else "")
