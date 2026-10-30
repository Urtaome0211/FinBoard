"""Cash-flow forecast page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.models import ForecastPoint, MonthStats
from ...core.dates import short_month_label
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import (
    Card,
    ComboBox,
    Page,
    PageHeader,
    ValueLabel,
    clear_layout,
    divider,
)
from .components import StatCard
from ..charts import TrendChart


class ForecastRow(QFrame):
    def __init__(self, point: ForecastPoint, service: FinanceService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ListRow")
        self.setFixedHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(8)
        month = QLabel(short_month_label(point.month))
        month.setMinimumWidth(80)
        row.addWidget(month, 1)
        for value, tone, width in (
            (point.income, "income", 130),
            (point.expense, "expense", 130),
            (point.net, "income" if point.net >= 0 else "expense", 140),
            (point.ending_cash, "text" if point.ending_cash >= 0 else "expense", 140),
        ):
            label = ValueLabel(
                service.format(value, plus=value > 0 and tone == "income"),
                tone=tone,
                size=12,
                weight=500,
            )
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setFixedWidth(width)
            row.addWidget(label)


class ForecastPage(Page):
    def __init__(self, service: FinanceService, window: QWidget) -> None:
        super().__init__()
        self.service = service
        self.window = window
        header = PageHeader(t("现金流预测"), t("按定期交易和近 3 个月的非定期支出估算"))
        self.months_combo = ComboBox()
        for label, value in ((t("未来 3 个月"), 3), (t("未来 6 个月"), 6), (t("未来 12 个月"), 12)):
            self.months_combo.addItem(label, value)
        self.months_combo.setCurrentIndex(1)
        self.months_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        header.add_action(self.months_combo)
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.start_card = StatCard(t("当前可用现金"), "wallet")
        self.average_card = StatCard(t("平均月结余"), "trending-up", tone="income")
        self.low_card = StatCard(t("最低现金"), "alert", tone="warning")
        self.end_card = StatCard(t("期末现金"), "chart", tone="accent")
        for card in (self.start_card, self.average_card, self.low_card, self.end_card):
            stats.addWidget(card)
        self.body.addLayout(stats)

        chart_card = Card()
        chart_card.add_header(t("未来现金流曲线"), t("收入与支出按月对比"))
        self.chart = TrendChart()
        self.chart.setMinimumHeight(260)
        chart_card.body.addWidget(self.chart)
        self.body.addWidget(chart_card)

        table_card = Card()
        table_card.add_header(t("逐月预测"), t("期末现金 = 期初现金 + 收入 - 支出"))
        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        head.setSpacing(8)
        first = QLabel(t("月份"))
        first.setProperty("role", "muted")
        head.addWidget(first, 1)
        for title, width in (
            (t("收入"), 130),
            (t("支出"), 130),
            (t("净现金流"), 140),
            (t("期末现金"), 140),
        ):
            label = QLabel(title)
            label.setProperty("role", "muted")
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setFixedWidth(width)
            head.addWidget(label)
        table_card.body.addLayout(head)
        table_card.body.addWidget(divider())
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(0)
        table_card.body.addLayout(self.rows_layout)
        self.body.addWidget(table_card)

        note = QLabel(
            t(
                "预测假设：定期交易按计划入账；非定期收支取近 3 个月平均值；"
                "转账不计入现金流；投资账户和负债不参与期初现金。"
            )
        )
        note.setProperty("role", "faint")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.body.addStretch(1)

    def refresh(self) -> None:
        months = int(self.months_combo.currentData() or 6)
        points = self.service.cash_flow_forecast(months)
        start = self.service.liquid_balance()
        average = round(sum(point.net for point in points) / len(points)) if points else 0
        lowest = min([start] + [point.ending_cash for point in points])
        end = points[-1].ending_cash if points else start
        self.start_card.set_value(self.service.format(start))
        self.average_card.set_value(self.service.format(average, plus=True))
        self.low_card.set_value(self.service.format(lowest))
        self.end_card.set_value(self.service.format(end))
        self.average_card.set_value(
            self.service.format(average, plus=True),
            tone="income" if average >= 0 else "expense",
        )
        self.low_card.set_value(
            self.service.format(lowest),
            tone="expense" if lowest < 0 else "warning",
        )
        self.end_card.set_value(
            self.service.format(end),
            tone="income" if end >= 0 else "expense",
        )
        stats = [
            MonthStats(month=point.month, income=point.income, expense=point.expense)
            for point in points
        ]
        self.chart.set_data(stats)
        clear_layout(self.rows_layout)
        for point in points:
            self.rows_layout.addWidget(ForecastRow(point, self.service))
