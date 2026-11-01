"""Fixed-term deposit editor."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from ...core.dates import add_months
from ...core.models import Account
from ...core.money import (
    CURRENCIES,
    parse_amount,
    parse_rate_bp,
    term_deposit_interest,
)
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import ValueLabel
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)

TERMS = (3, 6, 12, 24, 36, 60)


class DepositDialog(QDialog):
    """Create a new fixed-term deposit."""

    def __init__(
        self,
        service: FinanceService,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.accounts = [
            account
            for account in service.repo.accounts()
            if not account.is_system and account.type in ("cash", "debit", "investment")
        ]
        self.setWindowTitle(t("新建定期存款"))
        self.setMinimumWidth(500)
        root = root_layout(self)
        header, _ = dialog_header(
            t("新建定期存款"),
            t("存入后从账户转出，到期确认后本金转回指定账户，利息单独记收入"),
            "target",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：一年期整存整取"))
        self.name_input.setText(t("定期存款 {date}", date=QDate.currentDate().toString("yyyy-MM-dd")))
        self.principal_input = QLineEdit()
        self.principal_input.setPlaceholderText("0.00")
        self.currency_combo = QComboBox()
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(f"{meta['symbol']}  {code} · {meta['name']}", code)
        self.currency_combo.setCurrentIndex(
            max(0, self.currency_combo.findData(service.currency))
        )
        self.rate_input = QLineEdit("3.00")
        self.rate_input.setPlaceholderText("3.00")
        self.term_combo = QComboBox()
        for months in TERMS:
            self.term_combo.addItem(t("{count} 个月", count=months), months)
        self.term_combo.setCurrentIndex(TERMS.index(12))
        self.start_edit = QDateEdit(QDate.currentDate())
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.early_rate_input = QLineEdit("0.20")
        self.early_rate_input.setPlaceholderText("0.20")
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(300)
        self.destination_combo = QComboBox()
        self.destination_combo.setMinimumWidth(300)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))

        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("存入金额")), self.principal_input)
        form.addRow(form_label(t("币种")), self.currency_combo)
        form.addRow(form_label(t("年利率")), self.rate_input)
        form.addRow(form_label(t("期限")), self.term_combo)
        form.addRow(form_label(t("存入日期")), self.start_edit)
        form.addRow(form_label(t("活期利率")), self.early_rate_input)
        form.addRow(form_label(t("转出账户")), self.source_combo)
        form.addRow(form_label(t("到期转入")), self.destination_combo)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = ValueLabel("", size=13, tone="muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.hint = QLabel(
            t("提前支取按活期利率和实际持有天数计息；到期后需在储蓄页确认支取。")
        )
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("创建存款"), cancel_text=t("取消")
        )
        save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button = save_button
        save_button.clicked.connect(self._save)
        root.addLayout(footer)

        self.currency_combo.currentIndexChanged.connect(self._load_accounts)
        self.term_combo.currentIndexChanged.connect(self._update_preview)
        self.start_edit.dateChanged.connect(self._update_preview)
        for field in (self.principal_input, self.rate_input, self.early_rate_input):
            field.textChanged.connect(self._update_preview)
        self._load_accounts()
        self.principal_input.setFocus()

    def _currency(self) -> str:
        return str(self.currency_combo.currentData() or "CNY")

    def _load_accounts(self) -> None:
        currency = self._currency()
        suitable = [account for account in self.accounts if account.currency == currency]
        destination_id = self.destination_combo.currentData()
        source_id = self.source_combo.currentData()
        for combo, keep in (
            (self.source_combo, source_id),
            (self.destination_combo, destination_id),
        ):
            combo.blockSignals(True)
            combo.clear()
            for account in suitable:
                combo.addItem(self._account_label(account), account.id)
            index = combo.findData(keep)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        if source_id is None or self.source_combo.currentData() != source_id:
            positive = next(
                (
                    index
                    for index, account in enumerate(suitable)
                    if account.balance > 0
                ),
                0,
            )
            self.source_combo.setCurrentIndex(positive)
        if self.source_combo.currentData() is not None:
            index = self.destination_combo.findData(self.source_combo.currentData())
            if (
                index >= 0
                and self.destination_combo.findData(destination_id) < 0
            ):
                self.destination_combo.setCurrentIndex(index)
        self._update_preview()

    def _account_label(self, account: Account) -> str:
        return f"{account.name} · {self.service.format_money(account.balance, account.currency)}"

    def _update_preview(self) -> None:
        try:
            principal = parse_amount(self.principal_input.text())
            rate = parse_rate_bp(self.rate_input.text())
            early = parse_rate_bp(self.early_rate_input.text())
        except ValueError:
            self.preview.setText(t("填写金额与利率后显示到期利息"))
            self.preview.set_tone("muted")
            return
        months = int(self.term_combo.currentData() or 12)
        start = self.start_edit.date().toString("yyyy-MM-dd")
        maturity = add_months(start, months)
        interest = term_deposit_interest(principal, rate, months)
        self.preview.setText(
            t("到期日 {date} · 利息 {interest} · 到期合计 {total}").format(
                date=maturity,
                interest=self.service.format_money(interest, self._currency()),
                total=self.service.format_money(principal + interest, self._currency()),
            )
        )
        self.preview.set_tone("muted")

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, t("请输入存款名称"))
            self.name_input.setFocus()
            return
        try:
            principal = parse_amount(self.principal_input.text())
            annual_rate = parse_rate_bp(self.rate_input.text())
            early_rate = parse_rate_bp(self.early_rate_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        source_id = self.source_combo.currentData()
        destination_id = self.destination_combo.currentData()
        if source_id is None or destination_id is None:
            show_error(self.error, t("请选择转出账户和到期转入账户"))
            return
        try:
            self.service.add_term_deposit(
                name,
                principal,
                currency=self._currency(),
                annual_rate_bp=annual_rate,
                term_months=int(self.term_combo.currentData() or 12),
                start_date=self.start_edit.date().toString("yyyy-MM-dd"),
                early_rate_bp=early_rate,
                source_account_id=int(source_id),
                destination_account_id=int(destination_id),
                note=self.note_input.text().strip(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


__all__ = ["DepositDialog"]
