"""Insights page: a readable snapshot of financial health and recent changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import month_label, month_of, shift_month, today
from ...i18n import t
from ...core.money import format_percentage
from ..charts import CategoryBars
from ..theme import colors
from ..widgets import Card, Page, PageHeader, ThemedButton, ValueLabel
from .components import StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


class InsightsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("洞察", "把账本变成可行动的结论")
        refresh = ThemedButton("刷新", "secondary", "sync")
        refresh.clicked.connect(self.refresh)
        header.add_action(refresh)
        self.header = header
        self.body.addWidget(header)

        top = QHBoxLayout()
        top.setSpacing(18)

        self.score_card = Card(padding=22, spacing=10)
        self.score_card.setFixedWidth(330)
        self.score_card.add_header("财务健康", "综合储蓄、应急金、负债与固定支出")
        self.score_value = ValueLabel("—", tone="primary", size=54, weight=700)
        self.score_card.body.addWidget(self.score_value)
        self.grade_label = QLabel("")
        self.grade_label.setProperty("role", "muted")
        self.score_card.body.addWidget(self.grade_label)
        self.score_bar = QProgressBar()
        self.score_bar.setRange(0, 100)
        self.score_bar.setTextVisible(False)
        self.score_bar.setFixedHeight(8)
        self.score_card.body.addWidget(self.score_bar)
        self.score_hint = QLabel("")
        self.score_hint.setWordWrap(True)
        self.score_hint.setProperty("role", "faint")
        self.score_card.body.addWidget(self.score_hint)
        self.score_card.body.addStretch(1)
        top.addWidget(self.score_card)

        metrics = QWidget()
        grid = QGridLayout(metrics)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(14)
        self.savings_card = StatCard("储蓄率", "savings", tone="income")
        self.emergency_card = StatCard("应急金", "shield", tone="primary")
        self.debt_card = StatCard("负债率", "loan", tone="warning")
        self.fixed_card = StatCard("固定支出占比", "target", tone="accent")
        for index, card in enumerate(
            (self.savings_card, self.emergency_card, self.debt_card, self.fixed_card)
        ):
            grid.addWidget(card, index // 2, index % 2)
        top.addWidget(metrics, 1)
        self.body.addLayout(top)

        middle = QHBoxLayout()
        middle.setSpacing(18)

        self.change_card = Card(padding=20, spacing=10)
        self.change_card.add_header("这个月的变化", "与上个月和净资产对比")
        self.change_layout = QVBoxLayout()
        self.change_layout.setSpacing(9)
        self.change_card.body.addLayout(self.change_layout)
        middle.addWidget(self.change_card, 1)

        self.attention_card = Card(padding=20, spacing=9)
        self.attention_card.add_header("值得关注", "按优先级排出的 3–5 条建议")
        self.attention_layout = QVBoxLayout()
        self.attention_layout.setSpacing(9)
        self.attention_card.body.addLayout(self.attention_layout)
        middle.addWidget(self.attention_card, 1)
        self.body.addLayout(middle)

        self.category_card = Card(padding=20, spacing=10)
        self.category_card.add_header("本月支出构成", "前 6 个分类，点击报表查看完整区间")
        self.category_bars = CategoryBars()
        self.category_bars.setMinimumHeight(220)
        self.category_card.body.addWidget(self.category_bars)
        self.body.addWidget(self.category_card)
        self.body.addStretch(1)

    def refresh(self) -> None:
        month = month_of(today())
        health = self.service.financial_health(month)
        money = self.service.format
        self.header.set_subtitle(
            f"{month_label(month)} · " + t("基于最近 3 个完整月和当前净资产")
        )
        self.score_value.setText(str(health.score))
        self.score_value.set_tone(
            "income" if health.score >= 70 else "warning" if health.score >= 55 else "expense"
        )
        self.grade_label.setText(t("等级 {grade} · 满分 100", grade=health.grade))
        self.score_bar.setValue(health.score)
        palette = colors()
        color = (
            palette.income
            if health.score >= 70
            else palette.warning
            if health.score >= 55
            else palette.expense
        )
        self.score_bar.setStyleSheet(
            f"QProgressBar {{ background: {palette.surface_alt}; border: none;"
            f" border-radius: 4px; }}"
            f" QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )
        if health.score >= 85:
            hint = t("结构健康，继续保持储蓄和低负债。")
        elif health.score >= 70:
            hint = t("整体稳健，优先补应急金或压缩固定支出。")
        elif health.score >= 55:
            hint = t("有改善空间，先看下面的「值得关注」。")
        else:
            hint = t("压力偏大，建议先稳住现金流和应急金。")
        self.score_hint.setText(hint)

        self.savings_card.set_value(
            f"{health.savings_rate:.1f}%",
            hint=t("本月结余 / 收入"),
            tone="income" if health.savings_rate >= 20 else "expense",
        )
        self.emergency_card.set_value(
            t("{months} 个月", months=f"{health.emergency_months:.1f}"),
            hint=t("现金可覆盖的月支出"),
            tone="primary" if health.emergency_months >= 3 else "warning",
        )
        self.debt_card.set_value(
            f"{health.debt_ratio:.1f}%",
            hint=t("负债 / 资产"),
            tone="expense" if health.debt_ratio > 50 else "text",
        )
        self.fixed_card.set_value(
            f"{health.fixed_ratio:.1f}%",
            hint=t("固定支出 / 月均收入"),
            tone="warning" if health.fixed_ratio > 40 else "text",
        )

        current = self.service.repo.month_stats(month)
        previous = self.service.repo.month_stats(shift_month(month, -1))
        points = self.service.repo.net_worth_history(2)
        net_before = points[0].net if len(points) > 1 else points[-1].net if points else 0
        net_now = points[-1].net if points else 0
        self._refresh_changes(current, previous, net_now, net_before, money)

        self._refresh_attention(health, current, money)
        breakdown = self.service.repo.category_breakdown(month, "expense")
        self.category_bars.set_data(
            breakdown[:6], total=sum(item.amount for item in breakdown)
        )

    def _refresh_changes(self, current, previous, net_now, net_before, money) -> None:
        while self.change_layout.count():
            item = self.change_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = [
            ("本月收入", current.income, previous.income, False),
            ("本月支出", current.expense, previous.expense, True),
            ("本月结余", current.net, previous.net, False),
            ("净资产", net_now, net_before, False),
        ]
        for label, value, before, inverse in rows:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            name = QLabel(t(label))
            name.setProperty("role", "muted")
            amount = QLabel(money(value, plus=(label != "本月支出")))
            amount.setProperty("role", "expense" if value < 0 else "text")
            change = QLabel(self._change_text(value, before, inverse=inverse))
            change.setProperty(
                "role",
                "faint"
                if value == before
                else "expense"
                if (value < before) != inverse
                else "income",
            )
            layout.addWidget(name, 1)
            layout.addWidget(amount)
            layout.addSpacing(12)
            layout.addWidget(change)
            self.change_layout.addWidget(row)
        self.change_layout.addStretch(1)

    @staticmethod
    def _change_text(value: int, before: int, *, inverse: bool) -> str:
        if before == 0:
            return "—"
        delta = (value - before) / abs(before) * 100
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        return f"{arrow} {abs(delta):.1f}%"

    def _refresh_attention(self, health, current, money) -> None:
        while self.attention_layout.count():
            item = self.attention_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items: list[str] = []
        if health.emergency_months < 3:
            target = max(0, health.average_expense * 6 - health.liquid)
            items.append(
                t("应急金只有 {months} 个月，补到 6 个月还需 {amount}。", months=f"{health.emergency_months:.1f}", amount=money(target))
            )
        if health.debt_ratio > 40:
            items.append(t("负债率 {ratio}%，优先偿还高利率负债。", ratio=f"{health.debt_ratio:.1f}%"))
        if health.fixed_ratio > 40:
            items.append(t("固定支出占收入 {ratio}%，可以检查订阅和可降级项目。", ratio=f"{health.fixed_ratio:.1f}%"))
        if not health.has_budget:
            items.append(t("本月还没有预算，先设一个支出上限更容易控制。"))
        elif health.budget_ratio > 100:
            items.append(t("本月预算已用 {ratio}%，注意剩余支出。", ratio=f"{health.budget_ratio:.0f}%"))
        if health.top_category:
            items.append(
                t("最大支出是「{name}」{amount}，占本月支出 {share}。", name=health.top_category, amount=money(health.top_category_amount), share=format_percentage(health.top_category_amount, current.expense))
                if current.expense
                else t("最大支出是「{name}」{amount}。", name=health.top_category, amount=money(health.top_category_amount))
            )
        if not items:
            items.append(t("本月没有明显风险项，保持当前节奏。"))
        for text in items[:5]:
            label = QLabel("• " + text)
            label.setWordWrap(True)
            label.setProperty("role", "muted")
            self.attention_layout.addWidget(label)
        self.attention_layout.addStretch(1)
