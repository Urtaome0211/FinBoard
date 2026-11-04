"""Savings goals and fixed-term deposits."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import SavingsGoal, TermDeposit
from ...core.service import FinanceService
from ...i18n import t
from ..dialogs import DepositDialog, GoalDepositDialog, GoalDialog
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


class TermDepositRow(QFrame):
    close_requested = Signal(object)

    def __init__(
        self,
        deposit: TermDeposit,
        service: FinanceService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.deposit = deposit
        self.setObjectName("ListRow")
        self.setMinimumHeight(98)
        palette = colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 8, 4, 8)
        row.setSpacing(14)
        row.addWidget(
            icon_label(
                "target",
                palette.primary,
                18,
                palette.primary_soft,
                box=38,
                radius=11,
            )
        )

        column = QVBoxLayout()
        column.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(deposit.name)
        name.setProperty("i18nSkip", True)
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        top.addWidget(name)
        if deposit.status == "closed":
            top.addWidget(Badge(t("已支取"), "neutral"))
        elif deposit.is_matured:
            top.addWidget(Badge(t("已到期"), "warning"))
        else:
            top.addWidget(Badge(t("存续中"), "primary"))
        meta = QLabel(
            t("{rate} · {months} 个月 · 到期 {date}").format(
                rate=deposit.annual_rate_text,
                months=deposit.term_months,
                date=deposit.maturity_date,
            )
        )
        meta.setProperty("role", "muted")
        top.addWidget(meta)
        top.addStretch(1)
        column.addLayout(top)

        if deposit.is_active:
            bar = progress_bar(0)
            bar.setFixedHeight(7)
            set_progress(bar, deposit.progress)
            column.addWidget(bar)
        else:
            closed = QLabel(
                t("已于 {date} 支取").format(date=deposit.closed_at)
                if deposit.closed_at
                else t("已支取")
            )
            closed.setProperty("role", "faint")
            column.addWidget(closed)
        row.addLayout(column, 1)

        values = QVBoxLayout()
        values.setSpacing(2)
        amount = ValueLabel(
            service.format_money(deposit.principal, deposit.currency),
            size=13,
            weight=600,
        )
        amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        if deposit.status == "closed":
            interest_text = t("已付利息 {amount}").format(
                amount=service.format_money(deposit.interest_paid, deposit.currency)
            )
        elif deposit.is_matured:
            interest_text = t("到期利息 {amount}").format(
                amount=service.format_money(deposit.maturity_interest, deposit.currency)
            )
        else:
            interest_text = t("预计利息 {amount}").format(
                amount=service.format_money(deposit.maturity_interest, deposit.currency)
            )
        interest = QLabel(interest_text)
        interest.setProperty("role", "faint")
        interest.setAlignment(Qt.AlignmentFlag.AlignRight)
        values.addWidget(amount)
        values.addWidget(interest)
        row.addLayout(values)

        if deposit.is_active:
            action = ThemedButton(
                t("确认支取") if deposit.is_matured else t("提前支取"),
                "primary" if deposit.is_matured else "secondary",
            )
            action.clicked.connect(lambda: self.close_requested.emit(deposit))
            row.addWidget(action)
        else:
            row.addSpacing(88)


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
        header = PageHeader(
            t("储蓄"),
            t("用定期存款锁定利率，或用储蓄目标为重要的事留出钱"),
        )
        add_deposit = ThemedButton(t("新建存款"), "primary", "plus")
        add_deposit.clicked.connect(self._add_deposit)
        header.add_action(add_deposit)
        add_goal = ThemedButton(t("新建目标"), "secondary", "plus")
        add_goal.clicked.connect(self._add_goal)
        header.add_action(add_goal)
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.deposit_card = StatCard(t("定期存款"), "target")
        self.interest_card = StatCard(t("预计利息"), "trending-up", tone="income")
        self.saved_card = StatCard(t("目标已存"), "income", tone="income")
        self.progress_card = StatCard(t("目标进度"), "check", tone="accent")
        for card in (
            self.deposit_card,
            self.interest_card,
            self.saved_card,
            self.progress_card,
        ):
            stats.addWidget(card)
        self.body.addLayout(stats)

        self.banner = QFrame()
        self.banner.setObjectName("SoftCard")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        banner_layout.setSpacing(12)
        banner_layout.addWidget(
            icon_label(
                "alert",
                colors().warning,
                size=18,
                background=colors().warning_soft,
                box=32,
                radius=9,
            )
        )
        self.banner_text = QLabel()
        self.banner_text.setProperty("role", "warning")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text, 1)
        self.banner.hide()
        self.body.addWidget(self.banner)

        self.deposit_card_widget = Card()
        top = QHBoxLayout()
        title = QLabel(t("定期存款"))
        title.setProperty("role", "sectionTitle")
        top.addWidget(title)
        self.deposit_hint = QLabel()
        self.deposit_hint.setProperty("role", "faint")
        top.addWidget(self.deposit_hint)
        top.addStretch(1)
        self.deposit_card_widget.body.addLayout(top)
        self.deposit_card_widget.body.addWidget(divider())
        self.deposit_layout = QVBoxLayout()
        self.deposit_layout.setSpacing(0)
        self.deposit_card_widget.body.addLayout(self.deposit_layout)
        self.deposit_empty = EmptyState(
            "target",
            t("还没有定期存款"),
            t("把闲钱存成定期，到期前随时可以看到进度和预计利息"),
            t("新建存款"),
            self._add_deposit,
        )
        self.deposit_card_widget.body.addWidget(self.deposit_empty)
        self.body.addWidget(self.deposit_card_widget)

        self.list_card = Card()
        title_row = QHBoxLayout()
        goal_title = QLabel(t("储蓄目标"))
        goal_title.setProperty("role", "sectionTitle")
        title_row.addWidget(goal_title)
        title_row.addStretch(1)
        self.list_card.body.addLayout(title_row)
        self.list_card.body.addWidget(divider())
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.list_card.body.addLayout(self.list_layout)
        self.body.addWidget(self.list_card)
        self.empty = EmptyState(
            "target",
            t("还没有储蓄目标"),
            t("把旅行、应急金或首付写下来"),
            t("新建目标"),
            self._add_goal,
        )
        self.body.addWidget(self.empty)
        self.body.addStretch(1)
        self.refresh()

    def _base(self, amount: int, currency: str, day: str) -> int:
        try:
            return self.service.to_base(amount, currency, day)
        except Exception:
            return amount

    def refresh(self) -> None:
        deposits = self.service.term_deposits()
        active = [deposit for deposit in deposits if deposit.is_active]
        principal = sum(
            self._base(deposit.principal, deposit.currency, deposit.start_date)
            for deposit in active
        )
        expected = sum(
            self._base(deposit.maturity_interest, deposit.currency, deposit.start_date)
            for deposit in active
        )
        matured = sum(1 for deposit in active if deposit.is_matured)
        self.banner.setVisible(bool(matured))
        self.banner_text.setText(
            t(
                "有 {count} 笔定期存款已到期，请确认支取。",
                count=matured,
            )
        )
        self.deposit_card.set_value(
            self.service.format(principal),
            hint=(
                t("{count} 笔已到期").format(count=matured)
                if matured
                else t("{count} 笔存续中").format(count=len(active))
            ),
        )
        self.interest_card.set_value(
            self.service.format(expected), hint=t("按当前利率估算")
        )

        goals = self.service.savings_goals()
        total = sum(goal.target_amount for goal in goals)
        saved = sum(goal.saved_amount for goal in goals)
        done = sum(1 for goal in goals if goal.completed)
        percent = min(100.0, saved / total * 100) if total else 0.0
        self.saved_card.set_value(self.service.format(saved))
        self.progress_card.set_value(
            f"{percent:.1f}%",
            hint=t("{done} / {count} 个目标已达成").format(
                done=done, count=len(goals)
            ),
        )

        clear_layout(self.deposit_layout)
        for deposit in deposits:
            row = TermDepositRow(deposit, self.service)
            row.close_requested.connect(self._close_deposit)
            self.deposit_layout.addWidget(row)
        has_deposits = bool(deposits)
        self.deposit_empty.setVisible(not has_deposits)
        self.deposit_hint.setText(
            t("{count} 笔存续中").format(count=len(active)) if has_deposits else ""
        )
        self.deposit_card_widget.setVisible(True)

        clear_layout(self.list_layout)
        for goal in goals:
            row = SavingsGoalRow(goal, self.service)
            row.edit_requested.connect(self._edit_goal)
            row.deposit_requested.connect(self._deposit_goal)
            row.delete_requested.connect(self._delete_goal)
            self.list_layout.addWidget(row)
        has_goals = bool(goals)
        self.list_card.setVisible(has_goals)
        self.empty.setVisible(not has_goals)

    def _add_deposit(self) -> None:
        DepositDialog(self.service, parent=self.window).exec()
        self.refresh()

    def _close_deposit(self, deposit: TermDeposit) -> None:
        matured = deposit.is_matured
        interest = deposit.maturity_interest if matured else deposit.early_interest()
        if matured:
            title = t("确认支取")
            message = t(
                "「{name}」已到期，本金 {principal} 和利息 {interest} 将转入「{account}」。"
            ).format(
                name=deposit.name,
                principal=self.service.format_money(deposit.principal, deposit.currency),
                interest=self.service.format_money(interest, deposit.currency),
                account=deposit.destination_account_name,
            )
        else:
            title = t("提前支取")
            message = t(
                "「{name}」尚未到期，将按活期利率 {rate} 和实际持有天数计息，预计利息 {interest}。"
            ).format(
                name=deposit.name,
                rate=deposit.early_rate_text,
                interest=self.service.format_money(interest, deposit.currency),
            )
        if not ConfirmDialog.confirm(
            self.window,
            title,
            message,
            ok_text=t("确认支取"),
            danger=not matured,
        ):
            return
        try:
            result = self.service.close_term_deposit(deposit.id)
        except ValueError as exc:
            ConfirmDialog.alert(self.window, t("支取失败"), str(exc))
            return
        self.refresh()
        self.window.notify(
            t("已支取 {amount}").format(
                amount=self.service.format_money(
                    int(result["total"]), deposit.currency
                )
            )
        )

    def _add_goal(self) -> None:
        GoalDialog(self.service, parent=self.window).exec()
        self.refresh()

    def _edit_goal(self, goal: SavingsGoal) -> None:
        GoalDialog(self.service, goal, parent=self.window).exec()
        self.refresh()

    def _deposit_goal(self, goal: SavingsGoal) -> None:
        GoalDepositDialog(self.service, goal, parent=self.window).exec()
        self.refresh()

    def _delete_goal(self, goal: SavingsGoal) -> None:
        if not ConfirmDialog.confirm(
            self.window,
            t("删除目标"),
            t("确定删除「{name}」？").format(name=goal.name),
            danger=True,
        ):
            return
        self.service.delete_savings_goal(goal.id)
        self.refresh()
