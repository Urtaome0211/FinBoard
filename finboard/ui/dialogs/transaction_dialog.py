"""Create or edit a single income / expense / transfer record."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

from ...core.fees import withdrawal_rule
from ...core.models import Transaction
from ...core.money import CURRENCIES, parse_amount
from ...core.rates import RateError
from ...core.service import FinanceService
from ..widgets import SegmentedControl
from .common import (
    color_icon,
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class TransactionDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        transaction: Transaction | None = None,
        *,
        default_kind: str = "expense",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.transaction = transaction
        self.setWindowTitle("编辑记录" if transaction else "记一笔")
        self.setModal(True)
        self.setMinimumWidth(570)
        self.setSizeGripEnabled(False)

        kind = transaction.kind if transaction else default_kind
        layout = root_layout(self)

        header, _ = dialog_header(
            "编辑记录" if transaction else "记一笔",
            "修改后账户余额会同步更新" if transaction else "记录一笔收入、支出或账户间转账",
            "edit" if transaction else "plus",
        )
        layout.addLayout(header)

        self.kind_control = SegmentedControl(
            [("支出", "expense"), ("收入", "income"), ("转账", "transfer")], kind
        )
        self.kind_control.setMaximumWidth(330)
        self.kind_control.changed.connect(self._kind_changed)
        layout.addWidget(self.kind_control)

        amount_row = QHBoxLayout()
        amount_row.setSpacing(8)
        self.amount_symbol = QLabel(service.symbol)
        self.amount_symbol.setProperty("role", "muted")
        self.amount_symbol.setStyleSheet("font-size: 24px; font-weight: 600;")
        self.amount_symbol.setMinimumWidth(30)
        self.amount_input = QLineEdit()
        self.amount_input.setObjectName("AmountInput")
        self.amount_input.setPlaceholderText("0.00")
        self.amount_input.setMaxLength(20)
        self.amount_input.setClearButtonEnabled(True)
        self.currency_combo = QComboBox()
        self.currency_combo.setFixedWidth(118)
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(f"{code} · {meta['name']}", code)
        amount_row.addWidget(self.amount_symbol, 0, Qt.AlignmentFlag.AlignVCenter)
        amount_row.addWidget(self.amount_input, 1)
        amount_row.addWidget(self.currency_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(amount_row)

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 4, 0, 0)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(13)
        self.form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())
        self.form.addRow(form_label("日期"), self.date_edit)

        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(240)
        self.form.addRow(form_label("账户"), self.account_combo)

        self.category_label = form_label("分类")
        self.category_combo = QComboBox()
        self.form.addRow(self.category_label, self.category_combo)

        self.to_label = form_label("转入账户")
        self.to_combo = QComboBox()
        self.form.addRow(self.to_label, self.to_combo)

        self.to_amount_label = form_label("到账金额")
        self.to_amount_input = QLineEdit()
        self.to_amount_input.setPlaceholderText("留空则按当日汇率自动折算")
        self.to_amount_input.setMaxLength(20)
        self.form.addRow(self.to_amount_label, self.to_amount_input)

        self.fee_label = form_label("手续费")
        self.fee_value = QLabel("—")
        self.fee_value.setProperty("role", "muted")
        self.fee_value.setWordWrap(True)
        self.form.addRow(self.fee_label, self.fee_value)
        self.fee_label.hide()
        self.fee_value.hide()

        self.payee_input = QLineEdit()
        self.payee_input.setPlaceholderText("例如：盒马鲜生、房东、公司")
        self.payee_input.setMaxLength(60)
        self.form.addRow(form_label("对方"), self.payee_input)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("可选备注，例如：周末聚餐")
        self.note_input.setMaxLength(200)
        self.form.addRow(form_label("备注"), self.note_input)
        layout.addLayout(self.form)

        self.preview = QLabel()
        self.preview.setProperty("role", "faint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.hint = QLabel(
            "转账不计入收支统计，只调整两个账户的余额。"
            "支付宝/微信钱包提现会按规则自动扣手续费，并计入支出。"
        )
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text="保存记录" if transaction else "记一笔"
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)

        self._load_accounts()
        self._load_categories()
        self._load_targets()
        if transaction:
            self._fill(transaction)
        else:
            currency = self._selected_account_currency()
            index = self.currency_combo.findData(currency)
            if index >= 0:
                self.currency_combo.setCurrentIndex(index)
        self._kind_changed(kind, initial=True)
        self.account_combo.currentIndexChanged.connect(self._account_changed)
        self.currency_combo.currentIndexChanged.connect(self._currency_changed)
        self.amount_input.textChanged.connect(self._update_preview)
        self.date_edit.dateChanged.connect(self._update_preview)
        self.to_combo.currentIndexChanged.connect(self._target_changed)
        self.to_amount_input.textChanged.connect(self._update_preview)
        self._currency_changed()
        QTimer.singleShot(0, self.amount_input.setFocus)

    def _selected_account_currency(self) -> str:
        account = self.service.repo.get_account(
            self.account_combo.currentData() or 0, include_archived=True
        ) if self.account_combo.currentData() else None
        return account.currency if account else "CNY"

    # ------------------------------------------------------------------
    def _load_accounts(self) -> None:
        accounts = self.service.repo.accounts(include_archived=True)
        ordered = [a for a in accounts if not a.archived] + [
            a for a in accounts if a.archived
        ]
        self.account_combo.clear()
        for account in ordered:
            label = account.name
            if account.archived:
                label += "（已归档）"
            label += "  " + self.service.format_money(
                account.balance, account.currency
            )
            self.account_combo.addItem(icon_for_account(account.icon_name), label, account.id)

    def _load_categories(self, select_id: int | None = None) -> None:
        kind = self.kind_control.value()
        if kind == "transfer":
            return
        current = select_id if select_id is not None else self.category_combo.currentData()
        self.category_combo.clear()
        for category in self.service.repo.categories(kind):
            self.category_combo.addItem(
                color_icon(category.color), category.name, category.id
            )
        if current is not None:
            index = self.category_combo.findData(current)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _load_targets(self) -> None:
        current = self.to_combo.currentData()
        source = self.account_combo.currentData()
        accounts = self.service.repo.accounts(include_archived=True)
        self.to_combo.clear()
        for account in accounts:
            if account.id == source:
                continue
            if account.archived and account.id != current:
                continue
            label = account.name + ("（已归档）" if account.archived else "")
            self.to_combo.addItem(
                icon_for_account(account.icon_name), label, account.id
            )
        if current is not None:
            index = self.to_combo.findData(current)
            if index >= 0:
                self.to_combo.setCurrentIndex(index)
        if self.transaction and self.transaction.to_account_id:
            index = self.to_combo.findData(self.transaction.to_account_id)
            if index >= 0:
                self.to_combo.setCurrentIndex(index)

    def _account_changed(self) -> None:
        if self.kind_control.value() == "transfer":
            self._load_targets()
        self._target_changed()

    def _target_changed(self, *_args) -> None:
        target_id = self.to_combo.currentData()
        if target_id:
            target = self.service.repo.get_account(target_id, include_archived=True)
            self.to_amount_input.setPlaceholderText(
                f"留空自动折算为 {target.currency}"
            )
        self._update_preview()

    def _currency_changed(self, *_args) -> None:
        code = self.currency_combo.currentData() or "CNY"
        symbol = CURRENCIES.get(code, CURRENCIES["CNY"])["symbol"]
        self.amount_symbol.setText(symbol)
        self._target_changed()

    def _fill(self, transaction: Transaction) -> None:
        self.amount_input.setText(
            f"{transaction.amount // 100}.{transaction.amount % 100:02d}"
        )
        index = self.currency_combo.findData(transaction.currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        parsed = QDate.fromString(transaction.date, "yyyy-MM-dd")
        if parsed.isValid():
            self.date_edit.setDate(parsed)
        index = self.account_combo.findData(transaction.account_id)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)
        self._load_categories(transaction.category_id)
        self._load_targets()
        index = self.to_combo.findData(transaction.to_account_id)
        if index >= 0:
            self.to_combo.setCurrentIndex(index)
        if transaction.kind == "transfer" and transaction.to_amount:
            self.to_amount_input.setText(
                f"{transaction.to_amount // 100}."
                f"{transaction.to_amount % 100:02d}"
            )
        self.payee_input.setText(transaction.payee)
        self.note_input.setText(transaction.note)
        self.kind_control.set_value(transaction.kind, emit=False)

    # ------------------------------------------------------------------
    def _update_preview(self, *_args) -> None:
        text = self.amount_input.text().strip()
        if not text:
            self._hide_fee()
            self._set_preview("输入金额后显示折算结果", "faint")
            return
        try:
            amount = parse_amount(text)
        except ValueError:
            self._hide_fee()
            self._set_preview("金额格式有误", "error")
            return
        currency = self.currency_combo.currentData() or "CNY"
        day = self.date_edit.date().toString("yyyy-MM-dd")
        parts: list[str] = []
        try:
            account = self.service.repo.get_account(
                self.account_combo.currentData(), include_archived=True
            )
            base = self.service.to_base(amount, currency, day)
            if currency != self.service.currency:
                parts.append(f"约 {self.service.format(base)}")
            posted = amount
            if account.currency != currency:
                posted = self.service.rate_store.convert(
                    amount, currency, account.currency, day
                )
                parts.append(
                    f"账户入账 {self.service.format_money(posted, account.currency)}"
                )
            if self.kind_control.value() == "transfer":
                target_id = self.to_combo.currentData()
                if target_id:
                    target = self.service.repo.get_account(
                        target_id, include_archived=True
                    )
                    if self.to_amount_input.text().strip():
                        received = parse_amount(self.to_amount_input.text())
                        parts.append(
                            f"转入 {self.service.format_money(received, target.currency)}"
                        )
                    else:
                        received = self.service.rate_store.convert(
                            amount, currency, target.currency, day
                        )
                        parts.append(
                            f"预计转入 "
                            f"{self.service.format_money(received, target.currency)}"
                        )
                rule = withdrawal_rule(account.name, account.currency)
                if rule:
                    fee = self.service.repo.withdrawal_fee(account.id, posted)
                    self.fee_label.show()
                    self.fee_value.show()
                    self.fee_value.setText(
                        f"{self.service.format_money(fee, account.currency)}"
                        f"（{rule.label}，最低 "
                        f"{self.service.format_money(rule.minimum_fee, 'CNY')}）"
                    )
                    parts.append(
                        f"实际扣款 {self.service.format_money(posted + fee, account.currency)}"
                    )
                else:
                    self._hide_fee()
        except RateError as exc:
            self._hide_fee()
            self._set_preview(f"汇率不可用：{exc}", "error")
            return
        except ValueError as exc:
            self._hide_fee()
            self._set_preview(str(exc), "error")
            return
        self._set_preview(" · ".join(parts) or "无需折算", "faint")

    def _hide_fee(self) -> None:
        self.fee_label.hide()
        self.fee_value.hide()

    def _set_preview(self, text: str, role: str) -> None:
        self.preview.setText(text)
        self.preview.setProperty("role", role)
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)

    # ------------------------------------------------------------------
    def _kind_changed(self, kind: str, initial: bool = False) -> None:
        is_transfer = kind == "transfer"
        self.category_label.setVisible(not is_transfer)
        self.category_combo.setVisible(not is_transfer)
        self.to_label.setVisible(is_transfer)
        self.to_combo.setVisible(is_transfer)
        self.to_amount_label.setVisible(is_transfer)
        self.to_amount_input.setVisible(is_transfer)
        self.hint.setVisible(is_transfer)
        if not is_transfer:
            self._hide_fee()
        if not initial:
            self._load_categories()
            if is_transfer:
                self._load_targets()
        self.error.hide()
        self._update_preview()

    def _save(self) -> None:
        kind = self.kind_control.value()
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.amount_input.setFocus()
            return
        account_id = self.account_combo.currentData()
        if not account_id:
            show_error(self.error, "请先选择一个账户")
            return
        category_id = None
        to_account_id = None
        to_amount = None
        if kind == "transfer":
            to_account_id = self.to_combo.currentData()
            if not to_account_id:
                show_error(self.error, "请选择转入账户")
                return
            if to_account_id == account_id:
                show_error(self.error, "转出账户和转入账户不能相同")
                return
            if self.to_amount_input.text().strip():
                try:
                    to_amount = parse_amount(self.to_amount_input.text())
                except ValueError as exc:
                    show_error(self.error, f"到账金额：{exc}")
                    self.to_amount_input.setFocus()
                    return
        else:
            category_id = self.category_combo.currentData()
            if not category_id:
                show_error(self.error, "请先在“分类”页添加一个分类")
                return
        fields = dict(
            date=self.date_edit.date().toString("yyyy-MM-dd"),
            kind=kind,
            amount=amount,
            currency=self.currency_combo.currentData() or "CNY",
            to_amount=to_amount,
            category_id=category_id,
            account_id=account_id,
            to_account_id=to_account_id,
            payee=self.payee_input.text().strip(),
            note=self.note_input.text().strip(),
        )
        try:
            if self.transaction:
                self.service.update_transaction(self.transaction.id, **fields)
            else:
                self.service.add_transaction(**fields)
        except (ValueError, RateError) as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


def icon_for_account(name: str):
    """Small wrapper so the row stays readable and the icon is themed."""
    from ..icons import icon
    from ..theme import colors

    return icon(name, colors().muted, 17)
