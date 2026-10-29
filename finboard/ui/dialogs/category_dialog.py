"""Create or edit a transaction category."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from ...core.models import DEFAULT_COLORS, Category
from ...core.service import FinanceService
from ..theme import colors
from ..widgets import Badge, SegmentedControl
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class CategoryDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        category: Category | None = None,
        *,
        default_kind: str = "expense",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.category = category
        self.setWindowTitle("编辑分类" if category else "新建分类")
        self.setModal(True)
        self.setMinimumWidth(470)
        self.setSizeGripEnabled(False)
        self._buttons: list[QPushButton] = []

        layout = root_layout(self)
        header, _ = dialog_header(
            "编辑分类" if category else "新建分类",
            "分类会用于统计报表和预算" if not category else "修改分类的名称与颜色",
            "edit" if category else "tag",
        )
        layout.addLayout(header)

        if category:
            row = QHBoxLayout()
            row.addWidget(form_label("分类类型"))
            row.addWidget(
                Badge(
                    category.kind_label,
                    "primary" if category.kind == "income" else "neutral",
                )
            )
            row.addStretch(1)
            layout.addLayout(row)
            self.kind_control = None
        else:
            self.kind_control = SegmentedControl(
                [("支出", "expense"), ("收入", "income")], default_kind
            )
            self.kind_control.setMaximumWidth(260)
            layout.addWidget(self.kind_control)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：宠物、咖啡、房租")
        self.name_input.setMaxLength(20)
        form.addRow(form_label("名称"), self.name_input)
        layout.addLayout(form)

        color_label = QLabel("颜色")
        color_label.setProperty("role", "muted")
        layout.addWidget(color_label)

        palette = colors()
        palette_colors = list(DEFAULT_COLORS)
        if category and category.color not in palette_colors:
            palette_colors.append(category.color)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.color_group = QButtonGroup(self)
        self.color_group.setExclusive(True)
        for index, color in enumerate(palette_colors):
            button = QPushButton()
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(color)
            button.setAccessibleName(f"颜色 {color}")
            button.setStyleSheet(
                "QPushButton {"
                f"background-color: {color}; border: 2px solid transparent;"
                "border-radius: 8px; padding: 0;"
                "}"
                f"QPushButton:hover {{ border: 2px solid {palette.border_strong}; }}"
                f"QPushButton:checked {{ border: 3px solid {palette.text}; }}"
            )
            self.color_group.addButton(button, index)
            self._buttons.append(button)
            grid.addWidget(button, index // 5, index % 5)
        if category:
            for index, color in enumerate(palette_colors):
                if color.lower() == category.color.lower():
                    self._buttons[index].setChecked(True)
                    break
        else:
            self._buttons[0].setChecked(True)
        layout.addLayout(grid)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text="保存分类" if category else "创建分类"
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)

        if category:
            self.name_input.setText(category.name)
        QTimer.singleShot(0, self.name_input.setFocus)

    def selected_color(self) -> str:
        checked = self.color_group.checkedId()
        button = self.color_group.button(checked) if checked >= 0 else None
        if button is None:
            return DEFAULT_COLORS[0]
        return button.toolTip()

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, "请输入分类名称")
            self.name_input.setFocus()
            return
        color = self.selected_color()
        try:
            if self.category:
                self.service.update_category(self.category.id, name=name, color=color)
            else:
                kind = self.kind_control.value() if self.kind_control else "expense"
                self.service.add_category(name, kind, color)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
