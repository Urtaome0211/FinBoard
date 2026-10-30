"""Overview page: net worth pie, monthly KPIs, trend and recent activity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.dates import month_label, month_of, today
from ...i18n import category_display, t, today_label
from ...core.models import BudgetLine
from ...core.money import percentage
from ..charts import DonutChart, TrendChart
from ..rows import TransactionRow
from ..theme import colors, tone_for_ratio
from ..widgets import (
    Card,
    EmptyState,
    Page,
    PageHeader,
    ThemedButton,
    ValueLabel,
    clear_layout,
    divider,
    progress_bar,
    set_progress,
)
from .components import LegendRow, StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


class DashboardPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window
        self._recent_rows: list[QWidget] = []

        header = PageHeader("总览", "")
        self.header = header
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.net_card = StatCard("净资产", "wallet", tone="primary")
        self.income_card = StatCard("本月收入", "trending-up", tone="income")
        self.expense_card = StatCard("本月支出", "trending-down", tone="expense")
        self.balance_card = StatCard("本月结余", "savings", tone="primary")
        for card in (
            self.net_card,
            self.income_card,
            self.expense_card,
            self.balance_card,
        ):
            stats.addWidget(card, 1)
        self.body.addLayout(stats)

        middle = QHBoxLayout()
        middle.setSpacing(18)
        self.worth_card = Card(padding=20, spacing=10)
        self.worth_card.setFixedWidth(392)
        self.worth_card.add_header("资产与负债", "存款与负债占总额的百分比")
        self.donut = DonutChart()
        self.donut.setFixedSize(196, 196)
        self.worth_card.body.addWidget(self.donut, 0, Qt.AlignmentFlag.AlignHCenter)
        self.asset_legend = LegendRow(colors().income, "存款 / 资产")
        self.liability_legend = LegendRow(colors().expense, "负债")
        self.worth_card.body.addWidget(self.asset_legend)
        self.worth_card.body.addWidget(self.liability_legend)
        self.worth_card.body.addStretch(1)
        middle.addWidget(self.worth_card)

        self.trend_card = Card(padding=20, spacing=8)
        trend_header = QHBoxLayout()
        trend_header.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title = QLabel("近 6 个月收支趋势")
        title.setProperty("role", "cardTitle")
        title_col.addWidget(title)
        hint = QLabel("收入与支出按月对比")
        hint.setProperty("role", "muted")
        title_col.addWidget(hint)
        trend_header.addLayout(title_col)
        trend_header.addStretch(1)
        self.trend_card.body.addLayout(trend_header)
        self.trend_chart = TrendChart()
        self.trend_card.body.addWidget(self.trend_chart, 1)
        middle.addWidget(self.trend_card, 1)
        self.body.addLayout(middle)

        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        self.recent_card = Card(padding=20, spacing=8)
        recent_action = ThemedButton("查看全部", "link", "arrow-right")
        recent_action.clicked.connect(lambda: self.window.navigate("transactions"))
        self.recent_card.add_header("最近记录", "点击可编辑", recent_action)
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setSpacing(0)
        self.recent_card.body.addLayout(self.recent_layout)
        self.recent_card.body.addStretch(1)
        bottom.addWidget(self.recent_card, 1)

        self.budget_card = Card(padding=20, spacing=8)
        self.budget_card.setFixedWidth(386)
        budget_action = ThemedButton("管理", "link", "arrow-right")
        budget_action.clicked.connect(lambda: self.window.navigate("budgets"))
        self.budget_card.add_header("本月预算", "实时统计本月支出", budget_action)
        self.budget_layout = QVBoxLayout()
        self.budget_layout.setSpacing(10)
        self.budget_card.body.addLayout(self.budget_layout)
        self.budget_card.body.addStretch(1)
        bottom.addWidget(self.budget_card)
        self.body.addLayout(bottom)
        self.body.addStretch(1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        month = month_of(today())
        stats = self.service.repo.month_stats(month)
        worth = self.service.repo.net_worth()
        money = self.service.format

        self.header.set_subtitle(
            f"{month_label(month)} · {today_label(today().month, today().day)}"
        )
        self.net_card.set_value(
            money(worth.net),
            hint=t(
                "资产 {assets} · 负债 {liabilities}",
                assets=money(worth.assets),
                liabilities=money(worth.liabilities),
            ),
            tone="expense" if worth.net < 0 else "text",
        )
        self.income_card.set_value(
            "+" + money(stats.income),
            hint=t("工资、理财及其他收入"),
            tone="income",
        )
        self.expense_card.set_value(
            money(stats.expense), hint=t("本月所有支出"), tone="expense"
        )
        self.balance_card.set_value(
            money(stats.net, plus=True),
            hint=t("储蓄率 {rate}%", rate=f"{stats.savings_rate:.1f}"),
            tone="income" if stats.net >= 0 else "expense",
        )

        total = worth.assets + worth.liabilities
        palette = colors()
        segments = []
        if worth.assets > 0:
            segments.append((t("存款 / 资产"), worth.assets, palette.income))
        if worth.liabilities > 0:
            segments.append((t("负债"), worth.liabilities, palette.expense))
        self.donut.set_data(
            segments,
            center_title=t("净资产"),
            center_value=money(worth.net),
            empty_text=t("还没有账户数据"),
        )
        self.asset_legend.set_data(
            money(worth.assets), f"{percentage(worth.assets, total):.1f}%"
        )
        self.liability_legend.set_data(
            money(worth.liabilities), f"{percentage(worth.liabilities, total):.1f}%"
        )
        self.trend_chart.set_data(self.service.repo.trend(6))
        self._refresh_recent()
        self._refresh_budget()

    def header_month(self) -> str:
        return month_of(today())

    def _refresh_recent(self) -> None:
        clear_layout(self.recent_layout)
        self._recent_rows.clear()
        transactions = self.service.repo.recent_transactions(6)
        if not transactions:
            self.recent_layout.addWidget(
                EmptyState(
                    "list",
                    t("还没有记录"),
                    t("点击“记一笔”，开始记录第一笔收支。"),
                    t("记一笔"),
                    lambda: self.window.open_transaction(),
                )
            )
            return
        for transaction in transactions:
            row = TransactionRow(transaction, self.service)
            row.clicked.connect(lambda item: self.window.open_transaction(item))
            self.recent_layout.addWidget(row)
            self._recent_rows.append(row)

    def _refresh_budget(self) -> None:
        clear_layout(self.budget_layout)
        month = month_of(today())
        lines = self.service.repo.budget_lines(month)
        if not lines:
            self.budget_layout.addWidget(
                EmptyState(
                    "target",
                    t("还没有设置预算"),
                    t("先给本月定一个支出上限，超支时会提醒你。"),
                    t("设置预算"),
                    lambda: self.window.navigate("budgets"),
                )
            )
            return
        overall = lines[0] if lines[0].is_overall else None
        if overall is None:
            overall = BudgetLine(0, month, 0, "本月总预算", "", 0, 0)
        amount = ValueLabel(self.service.format(overall.amount), tone="text", size=24, weight=700)
        self.budget_layout.addWidget(amount)
        meta = QLabel(
            t("已用 {used} · 超支 {amount}", used=self.service.format(overall.spent), amount=self.service.format(-overall.remaining))
            if overall.remaining < 0
            else t("已用 {used} · 剩余 {amount}", used=self.service.format(overall.spent), amount=self.service.format(overall.remaining))
        )
        meta.setProperty("role", "error" if overall.remaining < 0 else "muted")
        self.budget_layout.addWidget(meta)
        bar = progress_bar(0)
        self.budget_layout.addWidget(bar)
        ratio = overall.ratio * 100 if overall.amount else 0
        set_progress(bar, ratio)
        status = QLabel(
            t("已使用 {ratio}% · 已超支", ratio=f"{ratio:.0f}")
            if ratio > 100
            else t("已使用 {ratio}%", ratio=f"{ratio:.0f}")
        )
        status.setProperty("role", "error" if ratio > 100 else "muted")
        self.budget_layout.addWidget(status)

        categories = [line for line in lines if not line.is_overall]
        categories.sort(key=lambda line: line.ratio, reverse=True)
        if categories:
            self.budget_layout.addWidget(divider())
            for line in categories[:4]:
                self.budget_layout.addWidget(self._budget_row(line))

    def _budget_row(self, line: BudgetLine) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 2, 0, 2)
        column.setSpacing(5)
        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {line.color or colors().muted}; font-size: 10px;")
        top.addWidget(dot)
        name = QLabel(category_display(line.name))
        name.setProperty("role", "muted")
        top.addWidget(name)
        top.addStretch(1)
        value = QLabel(
            f"{self.service.format(line.spent)} / {self.service.format(line.amount)}"
        )
        value.setProperty("role", "error" if line.ratio > 1 else "faint")
        top.addWidget(value)
        column.addLayout(top)
        bar = progress_bar(0)
        bar.setFixedHeight(6)
        column.addWidget(bar)
        set_progress(bar, line.ratio * 100)
        return container
