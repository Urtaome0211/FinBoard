"""Small, keyboard-first transaction entry window."""

from __future__ import annotations
from ..fluent_controls import ComboBox, DateEdit, LineEdit

from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.money import CURRENCIES, format_cents, parse_amount
from ...core.service import FinanceService
from ...i18n import t
from ..localize import localize_widgets
from ..widgets import ComboBox, SegmentedControl
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class QuickEntryDialog(QDialog):
    """A compact expense/income form for the global shortcut."""

    def __init__(self, service: FinanceService, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.settings = QSettings("FinBoard", "FinBoard")
        self._applying_kind = False
        self.setWindowTitle(t("快速记账"))
        self.setMinimumWidth(520)
        root = root_layout(self)
        header, _ = dialog_header(
            t("快速记账"), t("按回车保存；金额、分类和账户即可完成一笔记账"), "transactions"
        )
        root.addLayout(header)

        self.kind_control = SegmentedControl(
            [(t("支出"), "expense"), (t("收入"), "income")], "expense"
        )
        self.kind_control.setMaximumWidth(260)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.kind_control)
        kind_row.addStretch(1)
        root.addLayout(kind_row)

        amount_row = QHBoxLayout()
        amount_row.setSpacing(8)
        self.currency_label = QLabel("CNY")
        self.currency_label.setProperty("role", "muted")
        self.currency_label.setFixedWidth(48)
        amount_row.addWidget(self.currency_label)
        self.amount_input = LineEdit()
        self.amount_input.setObjectName("AmountInput")
        self.amount_input.setPlaceholderText("0.00")
        self.amount_input.setMaxLength(20)
        amount_row.addWidget(self.amount_input, 1)
        root.addLayout(amount_row)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.account_combo = ComboBox()
        self.account_combo.setMinimumWidth(300)
        self.category_combo = ComboBox()
        self.category_combo.setMinimumWidth(300)
        self.payee_input = LineEdit()
        self.payee_input.setPlaceholderText(t("付款对象，可选"))
        self.payee_input.setMaxLength(60)
        self.date_edit = DateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.note_input = LineEdit()
        self.note_input.setPlaceholderText(t("备注，可选"))
        self.note_input.setMaxLength(200)
        form.addRow(form_label(t("账户")), self.account_combo)
        form.addRow(form_label(t("分类")), self.category_combo)
        form.addRow(form_label(t("对方")), self.payee_input)
        form.addRow(form_label(t("日期")), self.date_edit)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setProperty("role", "muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("保存并关闭"), cancel_text=t("取消")
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)

        self._load_accounts()
        self._load_categories()
        self.kind_control.changed.connect(self._kind_changed)
        self.account_combo.currentIndexChanged.connect(self._account_changed)
        for widget in (self.amount_input, self.payee_input, self.note_input):
            widget.textChanged.connect(self._update_preview)
        self.payee_input.editingFinished.connect(self._apply_rule)
        self.amount_input.setFocus()
        self._update_preview()

    def _current_account(self):
        return self.service.repo.get_account(self.account_combo.currentData())

    def _load_accounts(self) -> None:
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        preferred = self.settings.value("last/account_id", type=int)
        for account in self.service.repo.accounts():
            symbol = CURRENCIES.get(account.currency, {}).get("symbol", account.currency)
            label = f"{account.name} · {format_cents(account.balance, symbol)}"
            self.account_combo.addItem(label, account.id)
        if self.account_combo.count():
            index = self.account_combo.findData(preferred)
            self.account_combo.setCurrentIndex(max(0, index))
        self.account_combo.blockSignals(False)
        self._update_currency()

    def _update_currency(self) -> None:
        account = self._current_account()
        if account is not None:
            self.currency_label.setText(account.currency)

    def _load_categories(self, select_id: int | None = None) -> None:
        kind = self.kind_control.value()
        current = select_id
        if current is None:
            current = self.category_combo.currentData()
            if current is None:
                current = self.settings.value("last/category_id", type=int)
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        categories = self.service.repo.categories(kind)
        for category in categories:
            self.category_combo.addItem(category.name, category.id)
        if self.category_combo.count():
            index = self.category_combo.findData(current)
            self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.blockSignals(False)

    def _kind_changed(self, kind: str) -> None:
        if self._applying_kind:
            return
        self._load_categories()
        self._update_preview()

    def _account_changed(self, _index: int) -> None:
        self._update_currency()
        self._update_preview()

    def _apply_rule(self) -> None:
        payee = self.payee_input.text().strip()
        if not payee:
            return
        rule = self.service.match_category_rule(payee, self.kind_control.value())
        if rule is None:
            return
        index = self.category_combo.findData(rule.category_id)
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
            self._update_preview()

    def _update_preview(self) -> None:
        account = self._current_account()
        currency = account.currency if account is not None else "CNY"
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError:
            self.preview.setText(t("输入金额后显示预览"))
            return
        category = self.category_combo.currentText() or t("未分类")
        name = account.name if account is not None else ""
        symbol = CURRENCIES.get(currency, {}).get("symbol", currency)
        self.preview.setText(
            t("{kind} {amount} · {account} · {category}").format(
                kind=t("支出") if self.kind_control.value() == "expense" else t("收入"),
                amount=format_cents(amount, symbol),
                account=name,
                category=category,
            )
        )

    def _save(self) -> None:
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        account = self._current_account()
        if account is None:
            show_error(self.error, t("请选择账户"))
            return
        category_id = self.category_combo.currentData()
        if category_id is None:
            show_error(self.error, t("请选择分类"))
            return
        try:
            self.service.add_transaction(
                date=self.date_edit.getDate().toString("yyyy-MM-dd"),
                kind=self.kind_control.value(),
                amount=amount,
                account_id=account.id,
                category_id=int(category_id),
                payee=self.payee_input.text().strip(),
                note=self.note_input.text().strip(),
                currency=account.currency,
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.settings.setValue("last/account_id", account.id)
        self.settings.setValue("last/category_id", int(category_id))
        self.settings.sync()
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._save()
            return
        super().keyPressEvent(event)


def open_quick_entry(service: FinanceService, parent: QWidget | None = None) -> None:
    dialog = QuickEntryDialog(service, parent=parent)
    localize_widgets(dialog)
    dialog.exec()
