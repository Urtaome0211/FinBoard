"""One-off planned transaction editor."""

from __future__ import annotations
from ..fluent_controls import ComboBox, DateEdit, LineEdit

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QWidget,
)

from ...core.money import parse_amount
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


class PlannedDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        *,
        default_kind: str = "expense",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(t("计划交易"))
        self.setMinimumWidth(540)
        root = root_layout(self)
        header, _ = dialog_header(
            t("计划一笔未来收支"),
            t("用于首付、学费、年终奖等一次性项目，确认后才入账"),
            "calendar",
        )
        root.addLayout(header)

        self.kind_control = SegmentedControl(
            [(t("支出"), "expense"), (t("收入"), "income"), (t("转账"), "transfer")],
            default_kind,
        )
        self.kind_control.setMaximumWidth(330)
        self.kind_control.changed.connect(self._kind_changed)
        root.addWidget(self.kind_control, 0)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.date_edit = DateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.amount_input = LineEdit()
        self.amount_input.setPlaceholderText("0.00")
        self.account_combo = ComboBox()
        for account in service.repo.accounts():
            self.account_combo.addItem(
                f"{account.name} · {account.currency}", account.id
            )
        self.category_label = QLabel(t("分类"))
        self.category_label.setProperty("role", "muted")
        self.category_combo = ComboBox()
        self.to_label = QLabel(t("转入账户"))
        self.to_label.setProperty("role", "muted")
        self.to_combo = ComboBox()
        self.payee_input = LineEdit()
        self.payee_input.setPlaceholderText(t("例如：首付、学费、年终奖"))
        self.note_input = LineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))
        form.addRow(form_label(t("日期")), self.date_edit)
        form.addRow(form_label(t("金额")), self.amount_input)
        form.addRow(form_label(t("账户")), self.account_combo)
        form.addRow(self.category_label, self.category_combo)
        form.addRow(self.to_label, self.to_combo)
        form.addRow(form_label(t("对方 / 用途")), self.payee_input)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(self, self.error, save_text=t("保存计划"))
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)
        self.account_combo.currentIndexChanged.connect(self._load_targets)
        self._kind_changed(default_kind, initial=True)

    def _kind(self) -> str:
        return str(self.kind_control.value())

    def _kind_changed(self, kind: str, initial: bool = False) -> None:
        is_transfer = kind == "transfer"
        self.category_label.setVisible(not is_transfer)
        self.category_combo.setVisible(not is_transfer)
        self.to_label.setVisible(is_transfer)
        self.to_combo.setVisible(is_transfer)
        if not is_transfer:
            self._load_categories(initial=True)
        self._load_targets()
        self.amount_input.setFocus()

    def _load_categories(self, *, initial: bool = False) -> None:
        kind = self._kind()
        selected = self.category_combo.currentData()
        self.category_combo.clear()
        for category in self.service.repo.categories(kind=kind):
            self.category_combo.addItem(category.name, category.id)
        if not initial and selected is not None:
            index = self.category_combo.findData(selected)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)

    def _load_targets(self) -> None:
        source = self.account_combo.currentData()
        selected = self.to_combo.currentData()
        self.to_combo.clear()
        for account in self.service.repo.accounts():
            if account.id == source:
                continue
            self.to_combo.addItem(f"{account.name} · {account.currency}", account.id)
        if selected is not None:
            index = self.to_combo.findData(selected)
            if index >= 0:
                self.to_combo.setCurrentIndex(index)

    def _save(self) -> None:
        show_error(self.error, "")
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        if amount <= 0:
            show_error(self.error, t("金额必须大于 0"))
            return
        account_id = self.account_combo.currentData()
        if account_id is None:
            show_error(self.error, t("请选择账户"))
            return
        kind = self._kind()
        category_id = None if kind == "transfer" else self.category_combo.currentData()
        to_account_id = self.to_combo.currentData() if kind == "transfer" else None
        if kind == "transfer":
            if to_account_id is None:
                show_error(self.error, t("请选择转入账户"))
                return
            if to_account_id == account_id:
                show_error(self.error, t("转入账户不能与原账户相同"))
                return
        elif category_id is None:
            show_error(self.error, t("请选择分类"))
            return
        try:
            self.service.add_planned_transaction(
                date=self.date_edit.getDate().toString("yyyy-MM-dd"),
                kind=kind,
                amount=amount,
                account_id=int(account_id),
                category_id=category_id,
                to_account_id=to_account_id,
                payee=self.payee_input.text().strip(),
                note=self.note_input.text().strip(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


__all__ = ["PlannedDialog"]
