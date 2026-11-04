"""Reconcile an account against a statement balance."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import day_label, today_iso
from ...core.money import format_cents, parse_signed_amount
from ...i18n import t
from ..widgets import (
    Card,
    IconButton,
    ThemedButton,
    ValueLabel,
    divider,
)
from .common import dialog_footer, dialog_header, show_error, error_label, form_label, root_layout


class ReconcileDialog(QDialog):
    def __init__(self, service, account, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.setWindowTitle(t("账户对账"))
        self.resize(540, 540)
        self.setModal(True)

        layout = root_layout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        header, _ = dialog_header(
            t("账户对账"),
            f"{account.name} · {account.currency} · {t('核对账单余额并校准账本')}",
            "check",
        )
        layout.addLayout(header)

        summary = Card(padding=16, spacing=6)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._summary_block(t("当前账本余额"), self._money(account.balance)))
        row.addWidget(self._summary_block(t("账户类型"), t(account.type_label)))
        summary.body.addLayout(row)
        layout.addWidget(summary)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.statement_input = QLineEdit()
        self.statement_input.setPlaceholderText(
            t("输入银行/钱包显示的余额，例如 1250.00")
        )
        self.statement_input.setClearButtonEnabled(True)
        self.statement_input.textChanged.connect(self._update_preview)
        self.statement_input.returnPressed.connect(self._save)
        form.addRow(form_label(t("账单余额")), self.statement_input)
        self.date_edit = QDateEdit(QDate.fromString(today_iso(), "yyyy-MM-dd"))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow(form_label(t("对账日期")), self.date_edit)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：月末账单"))
        form.addRow(form_label(t("备注")), self.note_input)
        layout.addLayout(form)

        self.difference = ValueLabel(t("输入账单余额后显示差额"), tone="muted", size=14)
        self.difference.setWordWrap(True)
        layout.addWidget(self.difference)

        layout.addWidget(divider())
        history_title = QLabel(t("最近对账"))
        history_title.setProperty("role", "sectionTitle")
        layout.addWidget(history_title)
        self.history = QVBoxLayout()
        self.history.setSpacing(0)
        layout.addLayout(self.history)
        self._load_history()

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(self, self.error, save_text=t("保存对账"))
        save = footer.itemAt(footer.count() - 1).widget()
        save.clicked.connect(self._save)
        layout.addLayout(footer)

    def _money(self, cents: int) -> str:
        return self.service.format_money(cents, self.account.currency)

    @staticmethod
    def _summary_block(title: str, value: str) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        label = QLabel(title)
        label.setProperty("role", "faint")
        column.addWidget(label)
        text = QLabel(value)
        text.setProperty("role", "cardTitle")
        column.addWidget(text)
        return box

    def _parsed(self) -> int | None:
        text = self.statement_input.text().strip()
        if not text:
            return None
        try:
            return parse_signed_amount(text)
        except ValueError:
            return None

    def _update_preview(self) -> None:
        value = self._parsed()
        if value is None:
            self.difference.setText(t("输入账单余额后显示差额"))
            self.difference.set_tone("muted")
            return
        diff = value - self.account.balance
        if diff == 0:
            self.difference.setText(t("账实一致，无需调整"))
            self.difference.set_tone("income")
        else:
            self.difference.setText(
                t(
                    "将调整 {amount}，对账后余额为 {balance}",
                    amount=self._money(diff),
                    balance=self._money(value),
                )
            )
            self.difference.set_tone("warning" if diff < 0 else "income")

    def _load_history(self) -> None:
        while self.history.count():
            item = self.history.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        records = self.service.reconciliations(self.account.id, limit=4)
        if not records:
            empty = QLabel(t("还没有对账记录"))
            empty.setProperty("role", "faint")
            self.history.addWidget(empty)
            return
        for record in records:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 6, 0, 6)
            line.setSpacing(10)
            date_text = QLabel(day_label(record.date))
            date_text.setProperty("role", "muted")
            date_text.setFixedWidth(88)
            balance_text = QLabel(self._money(record.statement_balance))
            balance_text.setProperty("role", "cardTitle")
            balance_text.setMinimumWidth(110)
            diff_text = QLabel(
                t("差额 {amount}", amount=self._money(record.difference))
            )
            diff_text.setProperty(
                "role", "income" if record.difference >= 0 else "expense"
            )
            line.addWidget(date_text)
            line.addWidget(balance_text)
            line.addWidget(diff_text, 1)
            self.history.addWidget(row)

    def _save(self) -> None:
        value = self._parsed()
        if value is None:
            show_error(self.error, t("请输入有效的账单余额"))
            self.statement_input.setFocus()
            return
        self.error.hide()
        try:
            self.service.reconcile_account(
                self.account.id,
                value,
                day=self.date_edit.date().toString("yyyy-MM-dd"),
                note=self.note_input.text(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
