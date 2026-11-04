"""Amortization schedule and debt payoff planner."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.loans import PayoffPlan
from ...core.models import Debt
from ...core.money import parse_amount
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import ThemedButton
from .common import (
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class DebtScheduleDialog(QDialog):
    """Show the amortization table for a loan."""

    def __init__(
        self,
        service: FinanceService,
        debt: Debt,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.debt = debt
        self.setWindowTitle(t("还款计划"))
        self.setMinimumSize(760, 620)
        root = root_layout(self)
        header, _ = dialog_header(
            t("还款计划"),
            t("{name} · 剩余本金 {balance}", name=debt.account_name, balance=service.format(debt.outstanding)),
            "calendar",
        )
        root.addLayout(header)

        schedule = service.repo.debt_schedule(debt.account_id)
        total_interest = sum(item.interest for item in schedule)
        summary = QHBoxLayout()
        summary.setSpacing(18)
        for label, value in (
            (t("期数"), str(len(schedule))),
            (t("月供"), service.format(schedule[0].payment) if schedule else "—"),
            (t("总利息"), service.format(total_interest)),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            caption = QLabel(label)
            caption.setProperty("role", "muted")
            column.addWidget(caption)
            value_label = QLabel(value)
            value_label.setStyleSheet("font-size: 17px; font-weight: 700;")
            column.addWidget(value_label)
            summary.addLayout(column)
        summary.addStretch(1)
        root.addLayout(summary)

        table = QTableWidget(len(schedule), 6)
        table.setHorizontalHeaderLabels(
            [t("期数"), t("日期"), t("月供"), t("本金"), t("利息"), t("剩余本金")]
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, item in enumerate(schedule):
            values = (
                str(item.number),
                item.date,
                service.format(item.payment),
                service.format(item.principal),
                service.format(item.interest),
                service.format(item.balance),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if column
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                table.setItem(row, column, cell)
        root.addWidget(table, 1)
        self._add_close(root)


class PayoffDialog(QDialog):
    """Snowball / avalanche debt payoff simulator."""

    def __init__(
        self,
        service: FinanceService,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(t("清偿规划"))
        self.setMinimumSize(720, 600)
        root = root_layout(self)
        header, _ = dialog_header(
            t("清偿规划"),
            t("先还哪一笔、还要几个月，用雪球或雪崩法算清楚"),
            "trending-down",
        )
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.addWidget(form_label(t("每月额外还款")))
        self.extra_input = QLineEdit("0.00")
        self.extra_input.setFixedWidth(130)
        controls.addWidget(self.extra_input)
        controls.addWidget(form_label(t("策略")))
        self.method_combo = QComboBox()
        self.method_combo.addItem(t("雪崩法（先还高利率）"), "avalanche")
        self.method_combo.addItem(t("雪球法（先还小余额）"), "snowball")
        controls.addWidget(self.method_combo)
        run = ThemedButton(t("重新计算"), "secondary", "refresh")
        run.clicked.connect(self._calculate)
        controls.addWidget(run)
        controls.addStretch(1)
        root.addLayout(controls)

        self.error = error_label()
        root.addWidget(self.error)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([t("月份"), t("还款"), t("剩余负债")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self._add_close(root)
        self._calculate()

    def _add_close(self, root: QVBoxLayout) -> None:
        footer = QHBoxLayout()
        footer.addStretch(1)
        close = ThemedButton(t("关闭"), "secondary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _calculate(self) -> None:
        show_error(self.error, "")
        try:
            extra = parse_amount(self.extra_input.text())
            if extra < 0:
                raise ValueError(t("额外还款不能为负数"))
            plan = self.service.repo.debt_payoff_plan(
                extra_monthly=extra, method=str(self.method_combo.currentData())
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.summary.setText("")
            self.table.setRowCount(0)
            return
        self._render(plan)

    def _render(self, plan: PayoffPlan) -> None:
        if not plan.rows:
            self.summary.setText(t("当前没有需要清偿的负债。"))
            self.table.setRowCount(0)
            return
        self.summary.setText(
            t("预计 {months} 个月还清，总利息 {interest}；还款顺序：{order}").format(
                months=plan.months,
                interest=self.service.format(plan.total_interest),
                order=" → ".join(plan.order),
            )
        )
        self.table.setRowCount(len(plan.rows))
        for row, item in enumerate(plan.rows):
            for column, value in enumerate(
                (
                    item.month,
                    self.service.format(item.payments),
                    self.service.format(item.balances),
                )
            ):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, column, cell)


__all__ = ["DebtScheduleDialog", "PayoffDialog"]
