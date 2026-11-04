"""Set a monthly budget for the whole month or one expense category."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QLabel, QLineEdit

from ...core.dates import month_label
from ...core.models import BudgetLine
from ...core.money import format_cents, parse_amount
from ...core.service import FinanceService
from ...i18n import t
from ..icons import icon
from ..theme import colors
from .common import (
    color_icon,
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class BudgetDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        month: str,
        line: BudgetLine | None = None,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.month = month
        self.line = line
        self.setWindowTitle("编辑预算" if line else "设置预算")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setSizeGripEnabled(False)

        layout = root_layout(self)
        header, _ = dialog_header(
            "编辑预算" if line else "设置预算",
            f"{month_label(month)} · {t('预算用于跟踪当月支出')}",
            "edit" if line else "target",
        )
        layout.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        month_row = QLabel(month_label(month))
        form.addRow(form_label("月份"), month_row)

        self.category_combo = QComboBox()
        palette = colors()
        if line:
            self.category_combo.addItem(
                icon("target" if line.is_overall else "tag", palette.muted, 17),
                line.name + ("（总预算）" if line.is_overall else ""),
                line.category_id,
            )
            self.category_combo.setEnabled(False)
        else:
            self.category_combo.addItem(
                icon("target", palette.muted, 17), "本月总预算", 0
            )
            lines = service.repo.budget_lines(month)
            budgeted = {item.category_id for item in lines}
            for category in service.repo.categories("expense"):
                if category.id in budgeted:
                    continue
                self.category_combo.addItem(
                    color_icon(category.color), category.name, category.id
                )
        form.addRow(form_label("预算对象"), self.category_combo)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("0.00")
        self.amount_input.setMaxLength(20)
        form.addRow(form_label("预算金额"), self.amount_input)
        layout.addLayout(form)

        self.rollover_check = QCheckBox(t("结转到下月"))
        self.rollover_check.setToolTip(t("本月未用完的预算可以带到下个月继续使用"))
        layout.addWidget(self.rollover_check)

        if line:
            self.rollover_check.setChecked(line.rollover)
            spent = QLabel(f"本月已支出 {format_cents(line.spent, service.symbol)}")
            spent.setProperty("role", "error" if line.ratio >= 1 else "muted")
            layout.addWidget(spent)
            self.amount_input.setText(
                f"{line.amount // 100}.{line.amount % 100:02d}"
            )
        else:
            hint = QLabel("建议先设置总预算，再为主要支出分类单独设置上限。")
            hint.setProperty("role", "faint")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text="保存预算" if line else "设置预算"
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)
        self.amount_input.setFocus()

    def _save(self) -> None:
        try:
            amount = parse_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.amount_input.setFocus()
            return
        category_id = self.category_combo.currentData()
        if category_id is None:
            show_error(self.error, "请选择预算对象")
            return
        try:
            self.service.set_budget(
                self.month,
                category_id,
                amount,
                rollover=self.rollover_check.isChecked(),
            )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
