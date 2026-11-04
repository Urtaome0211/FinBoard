"""Liability overview: loans, credit cards and payoff planning."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import Debt
from ...core.service import FinanceService
from ...i18n import t
from ..dialogs import DebtDialog, DebtScheduleDialog, PayoffDialog
from ..theme import colors
from ..widgets import (
    Badge,
    Card,
    EmptyState,
    IconButton,
    Page,
    PageHeader,
    ThemedButton,
    clear_layout,
    divider,
    icon_label,
    progress_bar,
    set_progress,
)
from .components import StatCard


class DebtRow(QFrame):
    edit_requested = Signal(int)
    schedule_requested = Signal(object)

    def __init__(
        self,
        debt: Debt,
        service: FinanceService,
        *,
        next_payment: int = 0,
        cycle_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.debt = debt
        self.setObjectName("ListRow")
        self.setMinimumHeight(104)
        palette = colors()
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 8, 4, 8)
        row.setSpacing(14)
        row.addWidget(
            icon_label(
                "credit-card" if debt.is_credit else "wallet",
                palette.expense if debt.is_credit else palette.primary,
                18,
                palette.expense_soft if debt.is_credit else palette.primary_soft,
                box=38,
                radius=11,
            )
        )

        column = QVBoxLayout()
        column.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(debt.account_name)
        name.setProperty("i18nSkip", True)
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        top.addWidget(name)
        top.addWidget(Badge(t("信用卡") if debt.is_credit else t("贷款"), "warning" if debt.is_credit else "primary"))
        top.addStretch(1)
        column.addLayout(top)

        if debt.is_loan:
            meta = t("{rate} · {term} 期 · 月供 {payment}").format(
                rate=debt.rate_text,
                term=debt.term_months,
                payment=service.format(next_payment) if next_payment else "—",
            )
        else:
            meta = t("{rate} · 额度 {limit} · 账单日 {billing} / 还款日 {due}").format(
                rate=debt.rate_text,
                limit=service.format(debt.credit_limit),
                billing=debt.billing_day or "—",
                due=debt.due_day or "—",
            )
        meta_label = QLabel(meta)
        meta_label.setProperty("role", "muted")
        column.addWidget(meta_label)
        if cycle_text:
            cycle = QLabel(cycle_text)
            cycle.setProperty("role", "faint")
            column.addWidget(cycle)

        bar = progress_bar(0)
        if debt.is_loan:
            set_progress(bar, debt.paid_progress)
        else:
            set_progress(bar, debt.utilization, force_tone="expense" if debt.utilization > 70 else None)
        column.addWidget(bar)
        row.addLayout(column, 1)

        amount_col = QVBoxLayout()
        amount_col.setSpacing(3)
        amount = QLabel(service.format(debt.outstanding))
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount.setStyleSheet("font-size: 17px; font-weight: 700;")
        amount_col.addWidget(amount)
        hint = QLabel(
            t("已还 {percent}%", percent=f"{debt.paid_progress:.0f}%")
            if debt.is_loan
            else t("已用 {percent}%", percent=f"{debt.utilization:.0f}%")
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        hint.setProperty("role", "faint")
        amount_col.addWidget(hint)
        row.addLayout(amount_col)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        if debt.is_loan:
            schedule = ThemedButton(t("还款计划"), "secondary")
            schedule.clicked.connect(lambda: self.schedule_requested.emit(debt))
            actions.addWidget(schedule)
        edit = IconButton("edit", t("设置负债信息"), size=16)
        edit.clicked.connect(lambda: self.edit_requested.emit(debt.account_id))
        actions.addWidget(edit)
        row.addLayout(actions)


class DebtsPage(Page):
    def __init__(self, service: FinanceService, window: QWidget) -> None:
        super().__init__()
        self.service = service
        self.window = window
        header = PageHeader(
            t("负债"),
            t("把贷款和信用卡的利率、期限、账单日补齐，才知道还要还多久"),
        )
        plan = ThemedButton(t("清偿规划"), "primary", "trending-down")
        plan.clicked.connect(self._open_plan)
        header.add_action(plan)
        self.body.addWidget(header)
        self.plan_button = plan

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.balance_card = StatCard(t("负债余额"), "credit-card", tone="expense")
        self.monthly_card = StatCard(t("每月还款"), "calendar", tone="primary")
        self.rate_card = StatCard(t("加权年利率"), "chart", tone="accent")
        self.months_card = StatCard(t("预计还清"), "trending-down", tone="primary")
        for card in (
            self.balance_card,
            self.monthly_card,
            self.rate_card,
            self.months_card,
        ):
            stats.addWidget(card)
        self.body.addLayout(stats)

        self.card = Card()
        head = QHBoxLayout()
        title = QLabel(t("负债账户"))
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
            "credit-card",
            t("还没有负债账户"),
            t("先到账户页创建贷款或信用卡账户，再回来补充利率与还款信息"),
            t("去账户页"),
            lambda: self.window.navigate("accounts"),
        )
        self.body.addWidget(self.empty)
        self.body.addStretch(1)

    def _base(self, amount: int, currency: str) -> int:
        try:
            return self.service.to_base(amount, currency)
        except Exception:
            return amount

    def _open_plan(self) -> None:
        PayoffDialog(self.service, parent=self.window).exec()

    def _edit(self, account_id: int) -> None:
        account = self.service.repo.get_account(account_id)
        if account is None:
            return
        DebtDialog(self.service, account, parent=self.window).exec()

    def _schedule(self, debt: Debt) -> None:
        DebtScheduleDialog(self.service, debt, parent=self.window).exec()

    def refresh(self) -> None:
        debts = self.service.repo.debts()
        total = 0
        monthly = 0
        weighted = 0
        for debt in debts:
            base = self._base(debt.outstanding, debt.currency)
            total += base
            weighted += base * debt.annual_rate_bp
            if debt.is_loan:
                schedule = self.service.repo.debt_schedule(debt.account_id)
                monthly += self._base(
                    schedule[0].payment if schedule else 0, debt.currency
                )
            else:
                monthly += self._base(debt.min_payment, debt.currency)
        rate = weighted / total / 100 if total else 0.0
        plan = self.service.repo.debt_payoff_plan()
        self.balance_card.set_value(
            self.service.format(total),
            hint=t("{count} 个负债账户", count=len(debts)),
        )
        self.monthly_card.set_value(self.service.format(monthly), hint=t("按最低还款估算"))
        self.rate_card.set_value(f"{rate:.2f}%")
        self.months_card.set_value(
            t("{months} 个月", months=plan.months) if debts and plan.months else "—",
            hint=t("按当前最低还款估算"),
        )
        self.plan_button.setVisible(bool(debts))

        clear_layout(self.rows)
        for debt in debts:
            next_payment = 0
            cycle_text = ""
            if debt.is_loan:
                schedule = self.service.repo.debt_schedule(debt.account_id)
                next_payment = schedule[0].payment if schedule else 0
            else:
                cycle = self.service.repo.debt_credit_cycle(debt.account_id)
                if cycle is not None:
                    cycle_text = t("本期账单 {statement} · 到期 {due}（还剩 {days} 天）").format(
                        statement=cycle.statement_date,
                        due=cycle.due_date,
                        days=cycle.days_until_due,
                    )
            row = DebtRow(
                debt,
                self.service,
                next_payment=next_payment,
                cycle_text=cycle_text,
            )
            row.edit_requested.connect(self._edit)
            row.schedule_requested.connect(self._schedule)
            self.rows.addWidget(row)
        self.card.setVisible(bool(debts))
        self.empty.setVisible(not debts)
        self.hint.setText(t("{count} 个账户").format(count=len(debts)) if debts else "")
