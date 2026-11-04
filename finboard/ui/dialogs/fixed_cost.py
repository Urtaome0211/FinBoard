"""Fixed-expense / subscription audit."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.insights import FixedCost
from ...core.service import FinanceService
from ...i18n import category_display, t
from ..theme import colors
from ..widgets import (
    Card,
    EmptyState,
    ThemedButton,
    ValueLabel,
)
from .common import dialog_header, root_layout


class FixedCostRow(QFrame):
    def __init__(
        self, item: FixedCost, service: FinanceService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ListRow")
        self.setFixedHeight(60)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{colors().primary}; border-radius:4px;")
        row.addWidget(dot)

        name = QLabel(item.payee)
        name.setProperty("i18nSkip", True)
        name.setMinimumWidth(150)
        row.addWidget(name, 2)
        category = QLabel(category_display(item.category) or t("未分类"))
        category.setProperty("role", "muted")
        row.addWidget(category, 1)
        count = QLabel(t("近 {months} 个月 {count} 笔", months=item.months, count=item.count))
        count.setProperty("role", "faint")
        row.addWidget(count)
        monthly = ValueLabel(service.format(item.monthly), size=13, weight=600)
        monthly.setMinimumWidth(90)
        row.addWidget(monthly)
        annual = QLabel(service.format(item.annual))
        annual.setProperty("role", "muted")
        annual.setMinimumWidth(96)
        row.addWidget(annual)
        variation = QLabel(f"{item.variation * 100:.0f}%")
        variation.setProperty("role", "faint")
        variation.setMinimumWidth(44)
        row.addWidget(variation)


class FixedCostDialog(QDialog):
    def __init__(self, service: FinanceService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(t("固定支出体检"))
        self.setMinimumSize(760, 620)
        root = root_layout(self)

        header, _ = dialog_header(
            t("固定支出体检"),
            t("识别每月重复出现的支出，估算年度固定成本与收入占比"),
            "target",
        )
        root.addLayout(header)

        self.items = service.fixed_costs(12)
        monthly = sum(item.monthly for item in self.items)
        annual = monthly * 12
        trend = service.repo.trend(12)
        income = sum(point.income for point in trend)
        average_income = income // 12
        ratio = monthly / average_income * 100 if average_income else 0.0

        stats = QHBoxLayout()
        stats.setSpacing(12)
        for title, value in (
            (t("每月固定支出"), service.format(monthly)),
            (t("预计年度支出"), service.format(annual)),
            (t("平均月收入"), service.format(average_income)),
            (t("占收入"), f"{ratio:.1f}%"),
        ):
            card = Card(padding=14, spacing=4)
            label = QLabel(title)
            label.setProperty("role", "muted")
            card.body.addWidget(label)
            number = ValueLabel(value, size=18, weight=700)
            card.body.addWidget(number)
            stats.addWidget(card, 1)
        root.addLayout(stats)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.tip = QLabel(
            t("金额波动超过 20% 或出现不足 3 个月的支出不会被计入。")
        )
        self.tip.setProperty("role", "faint")
        root.addWidget(self.tip)

        if self.items:
            for item in self.items:
                self.list_layout.addWidget(FixedCostRow(item, service))
        else:
            self.list_layout.addWidget(
                EmptyState(
                    "target",
                    t("还没有发现固定支出"),
                    t("连续记录几个月后，订阅和固定账单会出现在这里。"),
                )
            )
        self.list_layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = ThemedButton(t("完成"), "primary")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)
