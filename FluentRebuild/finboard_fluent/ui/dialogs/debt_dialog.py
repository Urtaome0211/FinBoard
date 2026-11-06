"""Loan and credit-card profile editor."""

from __future__ import annotations
from ..fluent_controls import ComboBox, DateEdit, LineEdit, SpinBox

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account
from ...core.money import parse_amount, parse_rate_bp
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


class DebtDialog(QDialog):
    """Edit the loan or credit-card terms attached to an account."""

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
        debt = service.repo.get_debt(account.id)
        self.setWindowTitle(t("负债设置"))
        self.setMinimumWidth(520)
        root = root_layout(self)
        header, _ = dialog_header(
            t("负债设置"),
            t("为{account}补充利率、期限或账单信息，用于还款计划与提醒", account=account.name),
            "credit-card",
        )
        root.addLayout(header)

        self.loan_form = QWidget()
        loan_form = QFormLayout(self.loan_form)
        loan_form.setHorizontalSpacing(18)
        loan_form.setVerticalSpacing(12)
        self.principal_input = LineEdit()
        self.principal_input.setPlaceholderText("0.00")
        self.rate_input = LineEdit("0.00")
        self.term_input = SpinBox()
        self.term_input.setRange(1, 720)
        self.term_input.setValue(12)
        self.start_edit = DateEdit(QDate.currentDate())
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.method_combo = ComboBox()
        self.method_combo.addItem(t("等额本息"), "equal_payment")
        self.method_combo.addItem(t("等额本金"), "equal_principal")
        loan_form.addRow(form_label(t("贷款本金")), self.principal_input)
        loan_form.addRow(form_label(t("年利率")), self.rate_input)
        loan_form.addRow(form_label(t("还款期数")), self.term_input)
        loan_form.addRow(form_label(t("首次还款")), self.start_edit)
        loan_form.addRow(form_label(t("还款方式")), self.method_combo)
        root.addWidget(self.loan_form)

        self.credit_form = QWidget()
        credit_form = QFormLayout(self.credit_form)
        credit_form.setHorizontalSpacing(18)
        credit_form.setVerticalSpacing(12)
        self.limit_input = LineEdit()
        self.limit_input.setPlaceholderText("0.00")
        self.credit_rate_input = LineEdit("0.00")
        self.billing_input = SpinBox()
        self.billing_input.setRange(1, 28)
        self.billing_input.setValue(5)
        self.due_input = SpinBox()
        self.due_input.setRange(1, 28)
        self.due_input.setValue(20)
        self.min_input = LineEdit("10.00")
        credit_form.addRow(form_label(t("信用额度")), self.limit_input)
        credit_form.addRow(form_label(t("年利率")), self.credit_rate_input)
        credit_form.addRow(form_label(t("账单日")), self.billing_input)
        credit_form.addRow(form_label(t("还款日")), self.due_input)
        credit_form.addRow(form_label(t("最低还款比例")), self.min_input)
        root.addWidget(self.credit_form)

        self.note_input = LineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))
        note_row = QFormLayout()
        note_row.setHorizontalSpacing(18)
        note_row.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(note_row)

        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(self, self.error, save_text=t("保存负债信息"))
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)

        if debt is not None:
            self.note_input.setText(debt.note)
            if account.type == "loan":
                self.principal_input.setText(f"{debt.principal / 100:.2f}")
                self.rate_input.setText(f"{debt.annual_rate_bp / 100:.2f}")
                self.term_input.setValue(max(1, debt.term_months))
                self.start_edit.setDate(
                    QDate.fromString(debt.start_date, "yyyy-MM-dd")
                    if debt.start_date
                    else QDate.currentDate()
                )
                index = self.method_combo.findData(debt.payment_method)
                if index >= 0:
                    self.method_combo.setCurrentIndex(index)
            else:
                self.limit_input.setText(f"{debt.credit_limit / 100:.2f}")
                self.credit_rate_input.setText(f"{debt.annual_rate_bp / 100:.2f}")
                self.billing_input.setValue(debt.billing_day or 5)
                self.due_input.setValue(debt.due_day or 20)
                self.min_input.setText(f"{debt.min_payment_bp / 100:.2f}")

        self.loan_form.setVisible(account.type == "loan")
        self.credit_form.setVisible(account.type == "credit")
        self._update_save_text(account.type)

    def _update_save_text(self, kind: str) -> None:
        self.save_button.setText(t("保存贷款信息") if kind == "loan" else t("保存信用卡信息"))

    def _basis(self) -> tuple[int, int]:
        try:
            principal = parse_amount(self.principal_input.text())
            rate = parse_rate_bp(self.rate_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return 0, -1
        if principal <= 0:
            show_error(self.error, t("贷款本金必须大于 0"))
            return 0, -1
        return principal, rate

    def _credit_basis(self) -> tuple[int, int, int, int, int]:
        try:
            limit = parse_amount(self.limit_input.text())
            rate = parse_rate_bp(self.credit_rate_input.text())
            min_bp = parse_rate_bp(self.min_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return 0, 0, 0, 0, -1
        if limit <= 0:
            show_error(self.error, t("信用额度必须大于 0"))
            return 0, 0, 0, 0, -1
        if min_bp <= 0 or min_bp > 10_000:
            show_error(self.error, t("最低还款比例应在 0% 到 100% 之间"))
            return 0, 0, 0, 0, -1
        return limit, rate, self.billing_input.value(), self.due_input.value(), min_bp

    def _save(self) -> None:
        show_error(self.error, "")
        try:
            if self.account.type == "loan":
                principal, rate = self._basis()
                if rate < 0:
                    return
                self.service.save_debt(
                    self.account.id,
                    kind="loan",
                    principal=principal,
                    annual_rate_bp=rate,
                    term_months=self.term_input.value(),
                    start_date=self.start_edit.getDate().toString("yyyy-MM-dd"),
                    payment_method=str(self.method_combo.currentData()),
                    note=self.note_input.text().strip(),
                )
            else:
                limit, rate, billing, due, min_bp = self._credit_basis()
                if rate < 0:
                    return
                self.service.save_debt(
                    self.account.id,
                    kind="credit",
                    annual_rate_bp=rate,
                    credit_limit=limit,
                    billing_day=billing,
                    due_day=due,
                    min_payment_bp=min_bp,
                    note=self.note_input.text().strip(),
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


__all__ = ["DebtDialog"]
