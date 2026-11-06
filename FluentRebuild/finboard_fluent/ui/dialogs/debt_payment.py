"""Repayment recording and history for loans and credit cards."""

from __future__ import annotations
from ..fluent_controls import ComboBox, DateEdit, LineEdit, TableWidget

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account, Debt
from ...core.money import parse_amount
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import ThemedButton
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class DebtPaymentDialog(QDialog):
    """Record one repayment against a liability account."""

    def __init__(
        self,
        service: FinanceService,
        account: Account,
        debt: Debt,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.debt = debt
        self.result_data: dict[str, object] | None = None
        self.setWindowTitle(t("记录还款"))
        self.setMinimumWidth(540)

        root = root_layout(self)
        header, _ = dialog_header(
            t("记录还款"),
            t(
                "{name} · 剩余 {balance} · 月利率 {rate}",
                name=account.name,
                balance=service.format(debt.outstanding),
                rate=f"{debt.annual_rate_bp / 100 / 12:.4f}%",
            ),
            "credit-card",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.amount_input = LineEdit()
        self.amount_input.setPlaceholderText("0.00")
        self.amount_input.textChanged.connect(self._update_preview)
        form.addRow(form_label(t("还款金额")), self.amount_input)

        self.date_edit = DateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow(form_label(t("还款日期")), self.date_edit)

        self.source_combo = ComboBox()
        self.source_combo.setMinimumWidth(300)
        self._load_sources()
        form.addRow(form_label(t("资金来源")), self.source_combo)

        self.note_input = LineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setProperty("role", "muted")
        root.addWidget(self.preview)
        self.error = error_label()
        root.addWidget(self.error)

        footer = dialog_footer(self, self.error, save_text=t("确认还款"))
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)
        self.amount_input.setText(f"{self._default_amount() / 100:.2f}")
        self._update_preview()
        if self.debt.outstanding <= 0:
            self.amount_input.setReadOnly(True)
            self.save_button.setEnabled(False)
            self.preview.setText(t("这笔负债已经还清"))

    def _default_amount(self) -> int:
        if self.debt.is_loan:
            schedule = self.service.repo.debt_schedule(self.account.id)
            if schedule:
                return min(self.debt.outstanding, schedule[0].payment)
        return min(self.debt.outstanding, max(1, self.debt.min_payment))

    def _load_sources(self) -> None:
        best_index = -1
        best_balance = 0
        for account in self.service.repo.accounts():
            if account.archived or account.is_system:
                continue
            if account.type not in ("cash", "debit", "investment"):
                continue
            if account.currency != self.account.currency:
                continue
            self.source_combo.addItem(
                t("{name} · 可用 {amount}").format(
                    name=account.name,
                    amount=self.service.format(account.cash_balance),
                ),
                account.id,
            )
            if account.cash_balance > best_balance:
                best_balance = account.cash_balance
                best_index = self.source_combo.count() - 1
        if self.source_combo.count() == 0:
            self.source_combo.addItem(t("没有可用的资金来源"), None)
        elif best_index >= 0:
            self.source_combo.setCurrentIndex(best_index)

    def _update_preview(self) -> None:
        show_error(self.error, "")
        text = self.amount_input.text().strip()
        if not text:
            self.preview.setText(t("输入还款金额后显示本金与利息拆分。"))
            return
        try:
            amount = parse_amount(text)
            split = self.service.debt_payment_preview(self.account.id, amount)
        except ValueError as exc:
            self.preview.setText("")
            show_error(self.error, str(exc))
            return
        self.preview.setText(
            t(
                "本金 {principal} · 利息 {interest} · 还款后剩余 {outstanding}",
                principal=self.service.format(split["principal"]),
                interest=self.service.format(split["interest"]),
                outstanding=self.service.format(
                    max(0, split["outstanding"] - split["principal"])
                ),
            )
        )

    def _save(self) -> None:
        show_error(self.error, "")
        try:
            amount = parse_amount(self.amount_input.text())
            source_id = self.source_combo.currentData()
            if not source_id:
                raise ValueError(t("请选择资金来源账户"))
            self.result_data = self.service.record_debt_payment(
                self.account.id,
                amount=amount,
                source_account_id=int(source_id),
                paid_on=self.date_edit.getDate().toString("yyyy-MM-dd"),
                note=self.note_input.text().strip(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


class DebtPaymentsDialog(QDialog):
    """Payment history for one liability account."""

    def __init__(
        self,
        service: FinanceService,
        account: Account,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.setWindowTitle(t("还款记录"))
        self.setMinimumSize(720, 520)

        root = root_layout(self)
        debt = service.repo.get_debt(account.id)
        header, _ = dialog_header(
            t("还款记录"),
            t("{name} · 剩余 {balance}", name=account.name, balance=service.format(debt.outstanding))
            if debt
            else account.name,
            "calendar",
        )
        root.addLayout(header)

        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)

        self.table = TableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [t("日期"), t("还款"), t("本金"), t("利息"), t("备注")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.pay_button = ThemedButton(t("记录还款"), "primary", "credit-card")
        self.pay_button.clicked.connect(self._record)
        footer.addWidget(self.pay_button)
        footer.addStretch(1)
        close = ThemedButton(t("关闭"), "secondary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)
        self._reload()

    def _reload(self) -> None:
        payments = self.service.debt_payments(self.account.id)
        total = sum(item.amount for item in payments)
        interest = sum(item.interest for item in payments)
        self.summary.setText(
            t("共 {count} 笔 · 累计还款 {total} · 利息 {interest}").format(
                count=len(payments),
                total=self.service.format(total),
                interest=self.service.format(interest),
            )
        )
        self.table.setRowCount(len(payments))
        for row, item in enumerate(payments):
            values = (
                item.paid_on,
                self.service.format(item.amount),
                self.service.format(item.principal),
                self.service.format(item.interest),
                item.note,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, column, cell)

    def _record(self) -> None:
        debt = self.service.repo.get_debt(self.account.id)
        if debt is None:
            return
        dialog = DebtPaymentDialog(self.service, self.account, debt, parent=self)
        if dialog.exec():
            self._reload()


__all__ = ["DebtPaymentDialog", "DebtPaymentsDialog"]
