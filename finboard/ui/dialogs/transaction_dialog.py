"""Create or edit a single income / expense / transfer record."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)

from ...core.fees import withdrawal_rule
from ...i18n import currency_display, t
from ...core.models import Transaction, TransactionFilter
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
        refund_of: Transaction | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.transaction = transaction
        self._refund_target = refund_of
        self._rule = None
        self._rule_tags: list[str] = []
        self._category_touched = bool(transaction)
        self._applying_rule = False
        self.setWindowTitle(t("编辑记录") if transaction else t("记一笔"))
        self.setModal(True)
        self.setMinimumWidth(570)
        self.setSizeGripEnabled(False)

        kind = (
            transaction.kind
            if transaction
            else ("income" if refund_of is not None else default_kind)
        )
        layout = root_layout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        header, _ = dialog_header(
            t("编辑记录") if transaction else t("记一笔"),
            t("修改后账户余额会同步更新")
            if transaction
            else t("记录一笔收入、支出或账户间转账"),
            "edit" if transaction else "plus",
        )
        layout.addLayout(header)

        self.kind_control = SegmentedControl(
            [
                (t("支出"), "expense"),
                (t("收入"), "income"),
                (t("转账"), "transfer"),
            ],
            kind,
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
        self.currency_combo.setFixedWidth(190)
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(
                currency_display(code, meta["symbol"], meta["name"]), code
            )
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
        self.form.addRow(form_label(t("日期")), self.date_edit)

        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(240)
        self.account_combo.setProperty("i18nSkip", True)
        self.form.addRow(form_label(t("来源账户")), self.account_combo)

        self.category_label = form_label(t("分类"))
        self.category_combo = QComboBox()
        self.form.addRow(self.category_label, self.category_combo)

        self.refund_check = QCheckBox(t("这是一笔退款（关联原支出）"))
        self.refund_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refund_check.toggled.connect(self._refund_toggled)
        self.form.addRow("", self.refund_check)
        self.refund_label = form_label(t("原支出"))
        self.refund_combo = QComboBox()
        self.refund_combo.setMinimumWidth(320)
        self.refund_combo.setProperty("i18nSkip", True)
        self.form.addRow(self.refund_label, self.refund_combo)
        self.refund_label.hide()
        self.refund_combo.hide()
        self.refund_check.hide()

        self.to_label = form_label(t("转入账户"))
        self.to_combo = QComboBox()
        self.to_combo.setProperty("i18nSkip", True)
        self.form.addRow(self.to_label, self.to_combo)

        self.to_amount_label = form_label(t("到账金额"))
        self.to_amount_input = QLineEdit()
        self.to_amount_input.setPlaceholderText(t("留空则按当日汇率自动折算"))
        self.to_amount_input.setMaxLength(20)
        self.form.addRow(self.to_amount_label, self.to_amount_input)

        self.fee_label = form_label(t("手续费"))
        self.fee_value = QLabel("—")
        self.fee_value.setProperty("role", "muted")
        self.fee_value.setWordWrap(True)
        self.form.addRow(self.fee_label, self.fee_value)
        self.fee_label.hide()
        self.fee_value.hide()

        self.waive_check = QCheckBox(t("本次豁免手续费"))
        self.waive_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.waive_check.toggled.connect(lambda _checked: self._update_preview())
        self.form.addRow("", self.waive_check)
        self.waive_check.hide()

        self.payee_input = QLineEdit()
        self.payee_input.setPlaceholderText(t("例如：盒马鲜生、房东、公司"))
        self.payee_input.setMaxLength(60)
        self.form.addRow(form_label(t("对方")), self.payee_input)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：周末聚餐"))
        self.note_input.setMaxLength(200)
        self.form.addRow(form_label(t("备注")), self.note_input)
        layout.addLayout(self.form)

        self.rule_hint = QLabel()
        self.rule_hint.setProperty("role", "faint")
        self.rule_hint.setWordWrap(True)
        self.rule_hint.hide()
        layout.addWidget(self.rule_hint)

        self.preview = QLabel()
        self.preview.setProperty("role", "faint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.hint = QLabel(
            t(
                "转账不计入收支统计，只调整两个账户的余额。"
                "支付宝/微信钱包提现会按规则自动扣手续费，并计入支出。"
            )
        )
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self,
            self.error,
            save_text=t("保存记录") if transaction else t("记一笔"),
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
        self.category_combo.currentIndexChanged.connect(self._category_changed)
        self.payee_input.editingFinished.connect(self._lookup_rule)
        if refund_of is not None:
            self._load_refunds(refund_of.id)
            self.refund_check.setChecked(True)
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
                t("留空自动折算为 {currency}", currency=target.currency)
            )
        self._update_preview()

    def _currency_changed(self, *_args) -> None:
        code = self.currency_combo.currentData() or "CNY"
        symbol = CURRENCIES.get(code, CURRENCIES["CNY"])["symbol"]
        self.amount_symbol.setText(symbol)
        self._target_changed()

    def _category_changed(self, *_args) -> None:
        if not self._applying_rule:
            self._category_touched = True

    def _lookup_rule(self) -> None:
        kind = self.kind_control.value()
        payee = self.payee_input.text().strip()
        if kind not in ("expense", "income") or not payee:
            self._rule = None
            self._rule_tags = []
            self.rule_hint.hide()
            return
        rule = self.service.match_category_rule(payee, kind)
        self._rule = rule
        self._rule_tags = list(rule.tags) if rule else []
        if rule is None:
            self.rule_hint.hide()
            return
        message = t(
            "已匹配规则「{pattern}」：{category}",
            pattern=rule.pattern,
            category=rule.category_name,
        )
        if rule.tags:
            message += t("；自动添加标签：{tags}", tags=rule.tag_text)
        self.rule_hint.setText(message)
        self.rule_hint.show()
        if not self._category_touched:
            index = self.category_combo.findData(rule.category_id)
            if index >= 0 and index != self.category_combo.currentIndex():
                self._applying_rule = True
                self.category_combo.setCurrentIndex(index)
                self._applying_rule = False

    def _load_refunds(self, select_id: int | None = None) -> None:
        current = select_id or self.refund_combo.currentData()
        self.refund_combo.clear()
        rows = list(
            self.service.repo.transactions(
                TransactionFilter(kind="expense", limit=500)
            )
        )
        if current is not None:
            matched = next((item for item in rows if item.id == int(current)), None)
            if matched is None:
                try:
                    matched = self.service.repo.get_transaction(int(current))
                except ValueError:
                    matched = None
            if matched is not None:
                rows = [matched] + [
                    item for item in rows if item.id != matched.id
                ]
        for item in rows:
            self.refund_combo.addItem(
                f"{item.date} · {item.title} · "
                f"{self.service.format_money(item.amount, item.currency)}",
                item.id,
            )
        if current is not None:
            index = self.refund_combo.findData(int(current))
            if index >= 0:
                self.refund_combo.setCurrentIndex(index)

    def _refund_toggled(self, checked: bool) -> None:
        if not checked:
            self.refund_label.hide()
            self.refund_combo.hide()
            return
        if self.refund_combo.count() == 0:
            self._load_refunds()
        self.refund_label.show()
        self.refund_combo.show()
        if self.refund_combo.currentData() is None and self.refund_combo.count():
            self.refund_combo.setCurrentIndex(0)

    def _sync_refund_visibility(self, kind: str) -> None:
        is_income = kind == "income"
        self.refund_check.setVisible(is_income)
        if not is_income:
            self.refund_check.setChecked(False)
            self.refund_label.hide()
            self.refund_combo.hide()
        elif self.refund_check.isChecked():
            self.refund_label.show()
            self.refund_combo.show()

    def _fill(self, transaction: Transaction) -> None:
        self._category_touched = True
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
        self.waive_check.setChecked(transaction.fee_waived)
        self.kind_control.set_value(transaction.kind, emit=False)
        if transaction.refund_of_id:
            self._load_refunds(transaction.refund_of_id)
            self.refund_check.setChecked(True)
        self._update_preview()

    # ------------------------------------------------------------------
    def _update_preview(self, *_args) -> None:
        text = self.amount_input.text().strip()
        if not text:
            self._hide_fee()
            self._set_preview(t("输入金额后显示折算结果"), "faint")
            return
        try:
            amount = parse_amount(text)
        except ValueError:
            self._hide_fee()
            self._set_preview(t("金额格式有误"), "error")
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
                parts.append(t("约 {amount}", amount=self.service.format(base)))
            posted = amount
            if account.currency != currency:
                posted = self.service.rate_store.convert(
                    amount, currency, account.currency, day
                )
                parts.append(
                    t(
                        "账户入账 {amount}",
                        amount=self.service.format_money(posted, account.currency),
                    )
                )
            if self.kind_control.value() == "transfer":
                target_id = self.to_combo.currentData()
                target = None
                if target_id:
                    target = self.service.repo.get_account(
                        target_id, include_archived=True
                    )

                rule = withdrawal_rule(account.name, account.currency)
                waived = self.waive_check.isChecked()
                fee = 0
                full = False
                self.to_amount_input.setEnabled(True)
                if rule:
                    fee = (
                        0
                        if waived
                        else self.service.repo.withdrawal_fee(account.id, posted)
                    )
                    exclude_id = self.transaction.id if self.transaction else None
                    available = self.service.available_balance(
                        account.id, exclude_id
                    )
                    full = bool(
                        not waived and fee and posted == available and posted > fee
                    )

                received = None
                if target is not None:
                    if full:
                        received = self.service.rate_store.convert(
                            posted - fee, account.currency, target.currency, day
                        )
                        parts.append(
                            t(
                                "预计转入 {amount}",
                                amount=self.service.format_money(
                                    received, target.currency
                                ),
                            )
                        )
                    elif self.to_amount_input.text().strip():
                        received = parse_amount(self.to_amount_input.text())
                        parts.append(
                            t(
                                "转入 {amount}",
                                amount=self.service.format_money(
                                    received, target.currency
                                ),
                            )
                        )
                    else:
                        received = self.service.rate_store.convert(
                            amount, currency, target.currency, day
                        )
                        parts.append(
                            t(
                                "预计转入 {amount}",
                                amount=self.service.format_money(
                                    received, target.currency
                                ),
                            )
                        )
                    self.to_amount_input.setEnabled(not full)

                if rule:
                    self.fee_label.show()
                    self.fee_value.show()
                    self.waive_check.show()
                    if waived:
                        self.fee_value.setText(
                            f"{self.service.format_money(0, account.currency)}"
                            f"（{t('已豁免')}）"
                        )
                    elif full:
                        self.fee_value.setText(
                            f"{self.service.format_money(fee, account.currency)}"
                            f"（{t('包含在提现金额中')}）"
                        )
                    else:
                        self.fee_value.setText(
                            f"{self.service.format_money(fee, account.currency)}"
                            f" ({t(rule.label)}, "
                            f"{t('最低 {amount}', amount=self.service.format_money(rule.minimum_fee, 'CNY'))})"
                        )
                    actual = posted if (waived or full) else posted + fee
                    parts.append(
                        t(
                            "实际扣款 {amount}",
                            amount=self.service.format_money(
                                actual, account.currency
                            ),
                        )
                    )
                else:
                    self._hide_fee()
                    self.to_amount_input.setEnabled(True)
        except RateError as exc:
            self._hide_fee()
            self._set_preview(
                t("汇率不可用：{error}", error=str(exc)), "error"
            )
            return
        except ValueError as exc:
            self._hide_fee()
            self._set_preview(str(exc), "error")
            return
        self._set_preview(" · ".join(parts) or t("无需折算"), "faint")

    def _hide_fee(self) -> None:
        self.fee_label.hide()
        self.fee_value.hide()
        self.waive_check.hide()

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
            self._category_touched = False
            self._rule = None
            self._rule_tags = []
            self.rule_hint.hide()
            self._lookup_rule()
            if is_transfer:
                self._load_targets()
        self._sync_refund_visibility(kind)
        self.error.hide()
        self._update_preview()

    def _save(self) -> None:
        kind = self.kind_control.value()
        self._lookup_rule()
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.amount_input.setFocus()
            return
        account_id = self.account_combo.currentData()
        if not account_id:
            show_error(self.error, t("请先选择一个账户"))
            return
        category_id = None
        to_account_id = None
        to_amount = None
        if kind == "transfer":
            to_account_id = self.to_combo.currentData()
            if not to_account_id:
                show_error(self.error, t("请选择转入账户"))
                return
            if to_account_id == account_id:
                show_error(self.error, t("转出账户和转入账户不能相同"))
                return
            if self.to_amount_input.text().strip():
                try:
                    to_amount = parse_amount(self.to_amount_input.text())
                except ValueError as exc:
                    show_error(self.error, t("到账金额：{error}", error=str(exc)))
                    self.to_amount_input.setFocus()
                    return
        else:
            category_id = self.category_combo.currentData()
            if not category_id:
                show_error(self.error, t("请先在“分类”页添加一个分类"))
                return
        fields = dict(
            date=self.date_edit.date().toString("yyyy-MM-dd"),
            kind=kind,
            amount=amount,
            currency=self.currency_combo.currentData() or "CNY",
            to_amount=to_amount,
            fee_waived=bool(self.waive_check.isChecked()),
            category_id=category_id,
            account_id=account_id,
            to_account_id=to_account_id,
            payee=self.payee_input.text().strip(),
            note=self.note_input.text().strip(),
        )
        if kind == "income" and self.refund_check.isChecked():
            refund_of_id = self.refund_combo.currentData()
            if not refund_of_id:
                show_error(self.error, t("请选择原支出记录"))
                return
            fields["refund_of_id"] = refund_of_id
        else:
            fields["refund_of_id"] = None
        used_rule = (
            self._rule
            if self._rule is not None and category_id == self._rule.category_id
            else None
        )
        if used_rule is not None and not self.transaction and used_rule.tags:
            fields["tags"] = list(used_rule.tags)
        try:
            if self.transaction:
                self.service.update_transaction(self.transaction.id, **fields)
            else:
                self.service.add_transaction(**fields)
        except (ValueError, RateError) as exc:
            show_error(self.error, str(exc))
            return
        if used_rule is not None:
            self.service.record_rule_hit(used_rule.id)
        self.accept()


def icon_for_account(name: str):
    """Small wrapper so the row stays readable and the icon is themed."""
    from ..icons import icon
    from ..theme import colors

    return icon(name, colors().muted, 17)
