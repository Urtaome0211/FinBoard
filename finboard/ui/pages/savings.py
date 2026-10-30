"""Savings goals page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import SavingsGoal
from ...core.service import FinanceService
from ...i18n import t
from ..dialogs import GoalDepositDialog, GoalDialog
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
    ValueLabel,
    clear_layout,
    divider,
    icon_label,
    progress_bar,
    set_progress,
)
from .components import StatCard


class SavingsGoalRow(QFrame):
    edit_requested = Signal(object)
    deposit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(
        self, goal: SavingsGoal, service: FinanceService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.goal = goal
        self.setObjectName("ListRow")
        self.setFixedHeight(94)
        palette = colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 8, 4, 8)
        row.setSpacing(14)
        row.addWidget(icon_label("target", palette.primary, 18, palette.primary_soft, box=38, radius=11))

        column = QVBoxLayout()
        column.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(goal.name)
        name.setProperty("i18nSkip", True)
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        top.addWidget(name)
        if goal.completed:
            top.addWidget(Badge(t("已达成"), "success"))
        date_text = goal.target_date or t("未设目标日期")
        date = QLabel(date_text)
        date.setProperty("role", "muted")
        top.addWidget(date)
        top.addStretch(1)
        progress = progress_bar(0)
        progress.setFixedHeight(7)
        set_progress(progress, goal.progress)
        column.addLayout(top)
        column.addWidget(progress)
        row.addLayout(column, 1)

        values = QVBoxLayout()
        values.setSpacing(2)
        amount = ValueLabel(
            f"{service.format(goal.saved_amount)} / {service.format(goal.target_amount)}",
            size=13,
            weight=600,
        )
        amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        remaining = QLabel(
            t("还差 {amount}").format(amount=service.format(goal.remaining))
            if not goal.completed
            else t("目标已完成")
        )
        remaining.setProperty("role", "faint")
        remaining.setAlignment(Qt.AlignmentFlag.AlignRight)
        values.addWidget(amount)
        values.addWidget(remaining)
        row.addLayout(values)

        actions = QHBoxLayout()
        actions.setSpacing(0)
        deposit = IconButton("plus", t("存入"), size=16)
        edit = IconButton("edit", t("编辑目标"), size=16)
        delete = IconButton("trash", t("删除目标"), size=16)
        for button in (deposit, edit, delete):
            button.setFixedSize(30, 30)
            actions.addWidget(button)
        deposit.clicked.connect(lambda: self.deposit_requested.emit(goal))
        edit.clicked.connect(lambda: self.edit_requested.emit(goal))
        delete.clicked.connect(lambda: self.delete_requested.emit(goal))
        row.addLayout(actions)


class SavingsPage(Page):
    def __init__(self, service: FinanceService, window: QWidget) -> None:
        super().__init__()
        self.service = service
        self.window = window
        header = PageHeader(t("储蓄目标"), t("为重要的事留出钱，慢慢靠近目标"))
        add = ThemedButton(t("新建目标"), "primary", "plus")
        add.clicked.connect(self._add)
        header.add_action(add)
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.total_card = StatCard(t("目标总额"), "target")
        self.saved_card = StatCard(t("已储蓄"), "income", tone="income")
        self.progress_card = StatCard(t("总进度"), "trending-up", tone="accent")
        self.done_card = StatCard(t("已达成"), "check", tone="success")
        for card in (self.total_card, self.saved_card, self.progress_card, self.done_card):
            stats.addWidget(card)
        self.body.addLayout(stats)

        self.list_card = Card()
        self.list_card.body.addWidget(divider())
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.list_card.body.addLayout(self.list_layout)
        self.body.addWidget(self.list_card)
        self.empty = EmptyState(
            "target", t("还没有储蓄目标"), t("把旅行、应急金或首付写下来"), t("新建目标"), self._add
        )
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

    def refresh(self) -> None:
        goals = self.service.savings_goals()
        total = sum(goal.target_amount for goal in goals)
        saved = sum(goal.saved_amount for goal in goals)
        done = sum(1 for goal in goals if goal.completed)
        percent = min(100.0, saved / total * 100) if total else 0.0
        self.total_card.set_value(self.service.format(total))
        self.saved_card.set_value(self.service.format(saved))
        self.progress_card.set_value(f"{percent:.1f}%")
        self.done_card.set_value(f"{done} / {len(goals)}")
        clear_layout(self.list_layout)
        for goal in goals:
            row = SavingsGoalRow(goal, self.service)
            row.edit_requested.connect(self._edit)
            row.deposit_requested.connect(self._deposit)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)
        has = bool(goals)
        self.list_card.setVisible(has)
        self.empty.setVisible(not has)

    def _add(self) -> None:
        GoalDialog(self.service, parent=self.window).exec()
        self.refresh()

    def _edit(self, goal: SavingsGoal) -> None:
        GoalDialog(self.service, goal, parent=self.window).exec()
        self.refresh()

    def _deposit(self, goal: SavingsGoal) -> None:
        GoalDepositDialog(self.service, goal, parent=self.window).exec()
        self.refresh()

    def _delete(self, goal: SavingsGoal) -> None:
        if not ConfirmDialog.confirm(
            self.window,
            t("删除目标"),
            t("确定删除「{name}」？").format(name=goal.name),
            danger=True,
        ):
            return
        self.service.delete_savings_goal(goal.id)
        self.refresh()
