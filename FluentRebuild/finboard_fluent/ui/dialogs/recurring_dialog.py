"""Create or edit a recurring transaction rule."""

from __future__ import annotations

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import normalize_day, today_iso
from ...core.fees import withdrawal_rule
from ...core.money import CURRENCIES, parse_amount
from ...i18n import t
from ..widgets import (
    ComboBox,
    SegmentedControl,
    clear_layout,
)
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)

FREQUENCIES = (
    ("每天", "daily"),
    ("每周", "weekly"),
    ("每月", "monthly"),
    ("每年", "yearly"),
)


class RecurringDialog(QDialog):
    def __init__(self, service, rule=None, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.rule = rule
        self.setWindowTitle(t("编辑定期交易") if rule else t("新建定期交易"))
        self.resize(570, 660)
        self.setModal(True)
        self._loading = True

        layout = root_layout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        header, _ = dialog_header(
            t("编辑定期交易") if rule else t("新建定期交易"),
            t("设置一次，到期后手动确认入账"),
            "calendar",
        )
        layout.addLayout(header)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：房租、工资、会员续费"))
        self.name_input.setMaxLength(60)

        self.kind_control = SegmentedControl(
            [
                (t("支出"), "expense"),
                (t("收入"), "income"),
                (t("转账"), "transfer"),
            ],
            rule.kind if rule else "expense",
        )
        self.kind_control.changed.connect(self._kind_changed)

        self.amount_input = QLineEdit()
        self.amount_input.setObjectName("AmountInput")
        self.amount_input.setPlaceholderText("0.00")
        self.currency_combo = ComboBox()
        for code, info in CURRENCIES.items():
            self.currency_combo.addItem(
                f"{code} · {info['symbol']} {info['name']}", code
            )
        self.currency_combo.setFixedWidth(190)
        amount_row = QHBoxLayout()
        amount_row.setSpacing(8)
        self.amount_symbol = QLabel("¥")
        self.amount_symbol.setProperty("role", "muted")
        amount_row.addWidget(self.amount_symbol)
        amount_row.addWidget(self.amount_input, 1)
        amount_row.addWidget(self.currency_combo)

        self.account_combo = ComboBox()
        self.account_combo.setProperty("i18nSkip", True)
        self.category_combo = ComboBox()
        self.to_combo = ComboBox()
        self.to_combo.setProperty("i18nSkip", True)

        self.frequency_combo = ComboBox()
        for label, value in FREQUENCIES:
            self.frequency_combo.addItem(t(label), value)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 365)
        self.interval_spin.setValue(1)
        self.interval_spin.setFixedWidth(74)
        self.interval_label = QLabel(t("个周期"))
        self.interval_label.setProperty("role", "muted")
        frequency_row = QHBoxLayout()
        frequency_row.setSpacing(8)
        frequency_row.addWidget(self.frequency_combo, 1)
        frequency_row.addWidget(self.interval_spin)
        frequency_row.addWidget(self.interval_label)
        frequency_row.addStretch(1)

        self.start_edit = QDateEdit(QDate.fromString(today_iso(), "yyyy-MM-dd"))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_check = QCheckBox(t("设置结束日期"))
        self.end_edit = QDateEdit(QDate.currentDate().addYears(1))
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.setEnabled(False)
        self.end_check.toggled.connect(self.end_edit.setEnabled)
        end_row = QHBoxLayout()
        end_row.setSpacing(8)
        end_row.addWidget(self.end_check)
        end_row.addWidget(self.end_edit, 1)

        self.payee_input = QLineEdit()
        self.payee_input.setPlaceholderText(t("例如：房东、公司、平台"))
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))
        self.waive_check = QCheckBox(t("本次提现豁免手续费"))
        self.active_check = QCheckBox(t("启用此规则"))
        self.active_check.setChecked(True)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("类型")), self.kind_control)
        form.addRow(form_label(t("金额")), amount_row)
        form.addRow(form_label(t("账户")), self.account_combo)
        self.category_label = form_label(t("分类"))
        form.addRow(self.category_label, self.category_combo)
        self.to_label = form_label(t("转入账户"))
        form.addRow(self.to_label, self.to_combo)
        form.addRow(form_label(t("重复")), frequency_row)
        form.addRow(form_label(t("开始日期")), self.start_edit)
        form.addRow(form_label(t("结束日期")), end_row)
        form.addRow(form_label(t("对方")), self.payee_input)
        form.addRow(form_label(t("备注")), self.note_input)
        layout.addLayout(form)

        options = QVBoxLayout()
        options.setSpacing(4)
        options.addWidget(self.waive_check)
        options.addWidget(self.active_check)
        layout.addLayout(options)

        self.hint = QLabel(t("到期后会在「定期」页面提示，确认入账才会写入收支。"))
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self,
            self.error,
            save_text=t("保存规则"),
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)

        self._load_accounts()
        self._load_categories()
        self._load_targets()
        if rule:
            self._fill(rule)
        else:
            self._sync_currency()
        self._kind_changed(self.kind_control.value(), initial=True)
        self._loading = False
        QTimer.singleShot(0, self.name_input.setFocus)

    # ------------------------------------------------------------------
    def _load_accounts(self) -> None:
        accounts = self.service.repo.accounts(include_archived=True)
        self.account_combo.clear()
        for account in accounts:
            if account.archived:
                continue
            self.account_combo.addItem(
                f"{account.name} · {account.currency}", account.id
            )

    def _load_categories(self) -> None:
        self.category_combo.clear()
        for category in self.service.repo.categories():
            self.category_combo.addItem(
                f"{category.name}", category.id
            )

    def _load_targets(self, *, exclude: int | None = None) -> None:
        current = self.to_combo.currentData()
        self.to_combo.clear()
        for account in self.service.repo.accounts(include_archived=False):
            if account.id == exclude:
                continue
            self.to_combo.addItem(
                f"{account.name} · {account.currency}", account.id
            )
        index = self.to_combo.findData(current)
        if index >= 0:
            self.to_combo.setCurrentIndex(index)

    def _selected_account(self):
        account_id = self.account_combo.currentData()
        if not account_id:
            return None
        return self.service.repo.get_account(int(account_id), include_archived=True)

    def _sync_currency(self) -> None:
        code = self.currency_combo.currentData() or "CNY"
        self.amount_symbol.setText(CURRENCIES.get(code, CURRENCIES["CNY"])["symbol"])
        rule = self._selected_account()
        can_waive = bool(
            rule
            and withdrawal_rule(rule.name, code) is not None
            and self.kind_control.value() == "transfer"
        )
        self.waive_check.setVisible(can_waive)
        if not can_waive:
            self.waive_check.setChecked(False)

    def _kind_changed(self, kind: object, *, initial: bool = False) -> None:
        is_transfer = kind == "transfer"
        self.category_label.setVisible(not is_transfer)
        self.category_combo.setVisible(not is_transfer)
        self.to_label.setVisible(is_transfer)
        self.to_combo.setVisible(is_transfer)
        self._sync_currency()

    def _fill(self, rule) -> None:
        self.name_input.setText(rule.name)
        self.kind_control.set_value(rule.kind, emit=False)
        self.amount_input.setText(
            self.service.format_money(rule.amount, rule.currency).replace(
                self.service.symbol, ""
            )
        )
        index = self.currency_combo.findData(rule.currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        index = self.account_combo.findData(rule.account_id)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)
        self._load_targets(exclude=rule.account_id)
        if rule.category_id:
            index = self.category_combo.findData(rule.category_id)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        if rule.to_account_id:
            index = self.to_combo.findData(rule.to_account_id)
            if index >= 0:
                self.to_combo.setCurrentIndex(index)
        index = self.frequency_combo.findData(rule.frequency)
        if index >= 0:
            self.frequency_combo.setCurrentIndex(index)
        self.interval_spin.setValue(rule.interval_count)
        self.start_edit.setDate(QDate.fromString(rule.start_date, "yyyy-MM-dd"))
        self.end_check.setChecked(bool(rule.end_date))
        if rule.end_date:
            self.end_edit.setDate(QDate.fromString(rule.end_date, "yyyy-MM-dd"))
        self.payee_input.setText(rule.payee)
        self.note_input.setText(rule.note)
        self.waive_check.setChecked(rule.fee_waived)
        self.active_check.setChecked(rule.active)
        self._sync_currency()

    # ------------------------------------------------------------------
    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, t("请输入名称"))
            self.name_input.setFocus()
            return
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.amount_input.setFocus()
            return
        account = self._selected_account()
        if account is None:
            show_error(self.error, t("请选择账户"))
            return
        kind = self.kind_control.value()
        category_id = (
            self.category_combo.currentData() if kind != "transfer" else None
        )
        to_account_id = self.to_combo.currentData() if kind == "transfer" else None
        if kind == "transfer" and not to_account_id:
            show_error(self.error, t("请选择转入账户"))
            return
        end_date = (
            self.end_edit.date().toString("yyyy-MM-dd")
            if self.end_check.isChecked()
            else None
        )
        fields = dict(
            name=name,
            kind=kind,
            amount=amount,
            account_id=account.id,
            category_id=category_id,
            to_account_id=to_account_id,
            payee=self.payee_input.text(),
            note=self.note_input.text(),
            fee_waived=self.waive_check.isChecked(),
            frequency=self.frequency_combo.currentData(),
            interval_count=self.interval_spin.value(),
            start_date=self.start_edit.date().toString("yyyy-MM-dd"),
            end_date=end_date,
            active=self.active_check.isChecked(),
            currency=self.currency_combo.currentData(),
        )
        try:
            if self.rule:
                self.service.update_recurring(self.rule.id, **fields)
            else:
                self.service.add_recurring(**fields)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
