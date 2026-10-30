"""Savings goal editor and quick deposit dialog."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from ...core.models import SavingsGoal
from ...core.money import format_cents, parse_signed_amount
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import ThemedButton, ValueLabel
from .common import dialog_footer, dialog_header, error_label, form_label, root_layout, show_error


class GoalDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        goal: SavingsGoal | None = None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.goal = goal
        self.setWindowTitle(t("编辑储蓄目标") if goal else t("新建储蓄目标"))
        self.setMinimumWidth(480)
        root = root_layout(self)
        header, _ = dialog_header(
            t("编辑储蓄目标") if goal else t("新建储蓄目标"),
            t("为一个具体愿望留出钱，例如旅行、应急金、首付"),
            "target",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：旅行基金、应急金、买房首付"))
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("0.00")
        self.saved_input = QLineEdit()
        self.saved_input.setPlaceholderText("0.00")
        self.saved_input.setText("0.00")
        self.date_check = QCheckBox(t("设置目标日期"))
        self.date_edit = QDateEdit(QDate.currentDate().addYears(1))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setEnabled(False)
        self.date_check.toggled.connect(self.date_edit.setEnabled)
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        date_row.addWidget(self.date_check)
        date_row.addWidget(self.date_edit, 1)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：每月存入 500"))

        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("目标金额")), self.target_input)
        form.addRow(form_label(t("已存金额")), self.saved_input)
        form.addRow(form_label(t("目标日期")), date_row)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = ValueLabel("", size=13, tone="muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("保存目标"), cancel_text=t("取消")
        )
        save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button = save_button
        save_button.clicked.connect(self._save)
        root.addLayout(footer)

        for field in (self.target_input, self.saved_input):
            field.textChanged.connect(self._update_preview)
        self.name_input.setFocus()
        if goal:
            self.name_input.setText(goal.name)
            self.target_input.setText(format_cents(goal.target_amount, ""))
            self.saved_input.setText(format_cents(goal.saved_amount, ""))
            self.note_input.setText(goal.note)
            if goal.target_date:
                self.date_check.setChecked(True)
                self.date_edit.setDate(QDate.fromString(goal.target_date, "yyyy-MM-dd"))
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            target = parse_signed_amount(self.target_input.text(), allow_zero=False)
            saved = parse_signed_amount(self.saved_input.text() or "0", allow_zero=True)
        except ValueError:
            self.preview.setText(t("填写目标金额与已存金额后显示进度"))
            self.preview.set_tone("muted")
            return
        remaining = max(0, target - saved)
        percent = min(100.0, saved / target * 100) if target else 0
        self.preview.setText(
            t("进度 {percent}% · 还差 {amount}").format(
                percent=f"{percent:.1f}",
                amount=self.service.format(remaining),
            )
        )
        self.preview.set_tone("income" if remaining == 0 else "muted")

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, t("请输入目标名称"))
            self.name_input.setFocus()
            return
        try:
            target = parse_signed_amount(self.target_input.text(), allow_zero=False)
            saved = parse_signed_amount(self.saved_input.text() or "0", allow_zero=True)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        if saved < 0:
            show_error(self.error, t("已存金额不能为负数"))
            return
        day = self.date_edit.date().toString("yyyy-MM-dd") if self.date_check.isChecked() else None
        try:
            if self.goal:
                self.service.update_savings_goal(
                    self.goal.id,
                    name=name,
                    target_amount=target,
                    saved_amount=saved,
                    target_date=day,
                    note=self.note_input.text().strip(),
                )
            else:
                self.service.add_savings_goal(
                    name,
                    target,
                    saved_amount=saved,
                    target_date=day,
                    note=self.note_input.text().strip(),
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


class GoalDepositDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        goal: SavingsGoal,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.goal = goal
        self.setWindowTitle(t("存入储蓄目标"))
        self.setMinimumWidth(380)
        root = root_layout(self)
        header, _ = dialog_header(
            t("存入储蓄目标"),
            f"{goal.name} · {t('当前已存')} {service.format(goal.saved_amount)}",
            "plus",
        )
        root.addLayout(header)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText(t("存入金额"))
        form.addRow(form_label(t("金额")), self.amount_input)
        root.addLayout(form)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(self, self.error, save_text=t("存入"), cancel_text=t("取消"))
        save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button = save_button
        save_button.clicked.connect(self._save)
        root.addLayout(footer)
        self.amount_input.setFocus()

    def _save(self) -> None:
        try:
            amount = parse_signed_amount(self.amount_input.text(), allow_zero=False)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        try:
            self.service.add_goal_funds(self.goal.id, amount)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


__all__ = ["GoalDepositDialog", "GoalDialog"]
