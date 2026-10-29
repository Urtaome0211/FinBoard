"""Create or edit an asset / liability account."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QLabel, QLineEdit

from ...core.models import ACCOUNT_TYPE_META, ACCOUNT_TYPES, Account
from ...core.money import CURRENCIES, parse_signed_amount
from ...core.service import FinanceService
from ..icons import icon
from ..theme import colors
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class AccountDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        account: Account | None = None,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.valuation_count = account.valuation_count if account else 0
        self.setWindowTitle("编辑账户" if account else "新建账户")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setSizeGripEnabled(False)

        layout = root_layout(self)
        header, _ = dialog_header(
            "编辑账户" if account else "新建账户",
            "修改金额会改变当前账户余额"
            if account
            else "资产填写余额；信用卡、贷款填写欠款金额",
            "edit" if account else "wallet",
        )
        layout.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：招商银行储蓄卡")
        self.name_input.setMaxLength(40)
        form.addRow(form_label("账户名称"), self.name_input)

        self.type_combo = QComboBox()
        palette = colors()
        for type_name in ACCOUNT_TYPES:
            meta = ACCOUNT_TYPE_META[type_name]
            suffix = "资产" if meta["group"] == "asset" else "负债"
            self.type_combo.addItem(
                icon(meta["icon"], palette.muted, 17),
                f"{meta['label']} · {suffix}",
                type_name,
            )
        form.addRow(form_label("账户类型"), self.type_combo)

        self.currency_combo = QComboBox()
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(f"{code} · {meta['name']}", code)
        self.currency_combo.setToolTip("账户余额以此币种记账；总览按每日汇率折算")
        form.addRow(form_label("账户币种"), self.currency_combo)

        self.opening_input = QLineEdit()
        self.opening_input.setPlaceholderText("0.00，例如：12000")
        self.opening_input.setMaxLength(20)
        self.opening_label = form_label("期初余额")
        form.addRow(self.opening_label, self.opening_input)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("可选备注，例如：工资卡")
        self.note_input.setMaxLength(120)
        form.addRow(form_label("备注"), self.note_input)
        layout.addLayout(form)

        self.hint = QLabel()
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.type_combo.currentIndexChanged.connect(self._sync_type_ui)
        self.currency_combo.currentIndexChanged.connect(self._sync_type_ui)

        if account:
            self.name_input.setText(account.name)
            index = self.type_combo.findData(account.type)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            index = self.currency_combo.findData(account.currency)
            if index >= 0:
                self.currency_combo.setCurrentIndex(index)
            if service.repo.account_usage(account.id) or self.valuation_count:
                self.currency_combo.setEnabled(False)
                self.currency_combo.setToolTip("已有记录，不能修改账户币种")
            if self.valuation_count:
                self.type_combo.setEnabled(False)
                self.type_combo.setToolTip("账户已有市值记录，不能更改类型")
                self.opening_input.setEnabled(False)
                self.opening_input.setToolTip("余额由最新市值与后续流水决定")
            opening = (
                abs(account.opening_balance)
                if account.is_liability
                else account.opening_balance
            )
            self.opening_input.setText(
                ("-" if opening < 0 else "")
                + f"{abs(opening) // 100}."
                + f"{abs(opening) % 100:02d}"
            )
            self.note_input.setText(account.note)

        self._sync_type_ui()
        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text="保存账户" if account else "创建账户"
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)

        self.name_input.setFocus()

    def _sync_type_ui(self, *_args) -> None:
        meta = ACCOUNT_TYPE_META.get(self.type_combo.currentData())
        liability = bool(meta and meta["group"] == "liability")
        currency = self.currency_combo.currentData() or "CNY"
        symbol = CURRENCIES.get(currency, CURRENCIES["CNY"])["symbol"]
        self.opening_label.setText("欠款金额" if liability else "期初余额")
        if self.valuation_count:
            self.opening_label.setText("期初余额")
            self.opening_input.setToolTip("余额由最新市值与后续流水决定")
            self.hint.setText(
                "该投资账户已使用每日市值：当前余额 = 最新市值 + 市值日之后的收支/转账。"
                "如需修正历史，请到账户页打开「市值记录」。"
            )
            return
        if liability:
            self.opening_input.setPlaceholderText(
                f"填写欠款正数，例如：12000（{currency}）"
            )
            hint = (
                "信用卡、贷款填写欠款金额即可（正数），系统会以负数余额计入负债。"
            )
            if self.account and self.account.is_liability and self.account.opening_balance > 0:
                hint += " 当前期初余额为正，直接保存就会按欠款记为负债。"
            self.hint.setText(hint)
        else:
            self.opening_input.setPlaceholderText(
                f"0.00，例如：12000（{currency}）"
            )
            self.hint.setText(
                f"账户以 {currency}（{symbol}）记账；余额 = 期初余额 + 收入 − 支出 ± 转账。"
            )

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, "请输入账户名称")
            self.name_input.setFocus()
            return
        try:
            opening = parse_signed_amount(self.opening_input.text() or "0")
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.opening_input.setFocus()
            return
        type_name = self.type_combo.currentData()
        meta = ACCOUNT_TYPE_META.get(type_name)
        if not meta:
            show_error(self.error, "请选择账户类型")
            return
        if meta["group"] == "liability" and opening > 0:
            opening = -opening
        note = self.note_input.text().strip()
        currency = self.currency_combo.currentData() or "CNY"
        try:
            if self.account:
                self.service.update_account(
                    self.account.id,
                    name=name,
                    type_=type_name,
                    opening_balance=opening,
                    note=note,
                    currency=currency,
                )
            else:
                self.service.add_account(
                    name,
                    type_name,
                    opening_balance=opening,
                    note=note,
                    currency=currency,
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
