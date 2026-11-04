"""Receivable / payable editor."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from ...core.money import CURRENCIES, parse_amount
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import SegmentedControl
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class ReceivableDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        *,
        default_direction: str = "receivable",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(t("往来款"))
        self.setMinimumWidth(500)
        root = root_layout(self)
        header, _ = dialog_header(
            t("记录往来款"),
            t("借给朋友或公司垫付，不污染收支报表；结清只改状态"),
            "transfer",
        )
        root.addLayout(header)

        self.direction_control = SegmentedControl(
            [(t("应收"), "receivable"), (t("应付"), "payable")],
            default_direction,
        )
        self.direction_control.setMaximumWidth(220)
        root.addWidget(self.direction_control, 0)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.counterparty_input = QLineEdit()
        self.counterparty_input.setPlaceholderText(t("对方名称"))
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("0.00")
        self.currency_combo = QComboBox()
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(f"{meta['symbol']}  {code} · {meta['name']}", code)
        self.currency_combo.setCurrentIndex(
            max(0, self.currency_combo.findData(service.currency))
        )
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.due_check = QCheckBox(t("设置到期日"))
        self.due_edit = QDateEdit(QDate.currentDate().addMonths(1))
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("yyyy-MM-dd")
        self.due_edit.setEnabled(False)
        self.due_check.toggled.connect(self.due_edit.setEnabled)
        self.account_combo = QComboBox()
        self.account_combo.addItem(t("不关联账户"), None)
        for account in service.repo.accounts():
            self.account_combo.addItem(
                f"{account.name} · {account.currency}", account.id
            )
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))
        form.addRow(form_label(t("对方")), self.counterparty_input)
        form.addRow(form_label(t("金额")), self.amount_input)
        form.addRow(form_label(t("币种")), self.currency_combo)
        form.addRow(form_label(t("日期")), self.date_edit)
        form.addRow(form_label(t("到期")), self.due_check)
        form.addRow("", self.due_edit)
        form.addRow(form_label(t("关联账户")), self.account_combo)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(self, self.error, save_text=t("保存往来款"))
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)
        self.counterparty_input.setFocus()

    def _save(self) -> None:
        show_error(self.error, "")
        counterparty = self.counterparty_input.text().strip()
        if not counterparty:
            show_error(self.error, t("请填写对方名称"))
            return
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        if amount <= 0:
            show_error(self.error, t("金额必须大于 0"))
            return
        try:
            self.service.add_receivable(
                direction=str(self.direction_control.value()),
                counterparty=counterparty,
                amount=amount,
                currency=str(self.currency_combo.currentData() or "CNY"),
                date=self.date_edit.date().toString("yyyy-MM-dd"),
                due_date=(
                    self.due_edit.date().toString("yyyy-MM-dd")
                    if self.due_check.isChecked()
                    else None
                ),
                account_id=self.account_combo.currentData(),
                note=self.note_input.text().strip(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


__all__ = ["ReceivableDialog"]
