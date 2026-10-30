"""Visual reports: net worth, spending mix, trends and rankings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import month_label, month_of, today
from ...core.exporters import export_excel, report_filename
from ...core.models import CategorySpend, PayeeSpend
from ...i18n import category_display, t
from ..charts import CategoryBars, DonutChart, TrendChart
from ..pdf_export import export_pdf, pdf_filename
from ..rows import ElidedLabel
from ..theme import colors
from ..widgets import (
    Card,
    ConfirmDialog,
    EmptyState,
    MonthCombo,
    Page,
    PageHeader,
    ThemedButton,
    ValueLabel,
    clear_layout,
)
from .components import LegendRow, StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


class RankRow(QFrame):
    def __init__(
        self, rank: int, payee: PayeeSpend, service, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ListRow")
        self.setFixedHeight(50)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(10)
        index = QLabel(f"{rank:02d}")
        index.setProperty("role", "faint")
        index.setFixedWidth(24)
        row.addWidget(index)
        payee_label = ElidedLabel(payee.payee or t("未填写"), size=13, weight=500)
        payee_label.setProperty("i18nSkip", True)
        row.addWidget(payee_label, 1)
        count = QLabel(t("{count} 笔", count=payee.count))
        count.setProperty("role", "muted")
        row.addWidget(count)
        amount = ValueLabel(service.format(payee.amount), size=13, weight=600)
        amount.setMinimumWidth(96)
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(amount)


class ReportsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("报表", "看懂资产负债结构与消费习惯")
        self.month_combo = MonthCombo(count=24)
        self.month_combo.set_month(month_of(today()))
        self.month_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        header.add_action(self.month_combo)
        self.export_button = ThemedButton("导出报表", "secondary", "download")
        self.export_button.clicked.connect(self._export_menu)
        header.add_action(self.export_button)
        self.header = header
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.income_card = StatCard("本月收入", "income", tone="income")
        self.expense_card = StatCard("本月支出", "expense", tone="expense")
        self.net_card = StatCard("本月结余", "savings", tone="primary")
        self.rate_card = StatCard("储蓄率", "trending-up", tone="primary")
        for card in (self.income_card, self.expense_card, self.net_card, self.rate_card):
            stats.addWidget(card, 1)
        self.body.addLayout(stats)

        donuts = QHBoxLayout()
        donuts.setSpacing(18)
        self.worth_card = Card(padding=20, spacing=10)
        self.worth_card.add_header("资产与负债", "存款、投资与欠款的比例")
        self.worth_chart = DonutChart()
        self.worth_chart.setMinimumHeight(220)
        self.worth_card.body.addWidget(self.worth_chart, 1)
        self.worth_legend = QVBoxLayout()
        self.worth_legend.setSpacing(8)
        self.asset_legend = LegendRow(colors().primary, "存款 / 资产")
        self.liability_legend = LegendRow(colors().expense, "负债")
        self.worth_legend.addWidget(self.asset_legend)
        self.worth_legend.addWidget(self.liability_legend)
        self.worth_card.body.addLayout(self.worth_legend)
        donuts.addWidget(self.worth_card, 1)

        self.expense_card_panel = Card(padding=20, spacing=10)
        self.expense_card_panel.add_header("本月支出构成", "按分类拆分")
        self.expense_chart = DonutChart()
        self.expense_chart.setMinimumHeight(220)
        self.expense_card_panel.body.addWidget(self.expense_chart, 1)
        self.expense_note = QLabel()
        self.expense_note.setProperty("role", "faint")
        self.expense_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.expense_card_panel.body.addWidget(self.expense_note)
        donuts.addWidget(self.expense_card_panel, 1)
        self.body.addLayout(donuts)

        self.trend_card = Card(padding=20, spacing=10)
        self.trend_card.add_header("近 12 个月收支趋势", "收入与支出按月对比")
        self.trend_chart = TrendChart()
        self.trend_card.body.addWidget(self.trend_chart)
        self.body.addWidget(self.trend_card)

        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        self.category_card = Card(padding=20, spacing=10)
        self.category_card.add_header("支出分类排行", "本月占比")
        self.category_bars = CategoryBars()
        self.category_card.body.addWidget(self.category_bars)
        bottom.addWidget(self.category_card, 3)

        self.payee_card = Card(padding=20, spacing=10)
        self.payee_card.add_header("消费对象 Top 5", "按金额排序")
        self.payee_list = QVBoxLayout()
        self.payee_list.setSpacing(0)
        self.payee_card.body.addLayout(self.payee_list)
        self.payee_card.body.addStretch(1)
        bottom.addWidget(self.payee_card, 2)
        self.body.addLayout(bottom)

        self.note = QLabel("转账只在账户之间移动资金，不计入收入和支出。")
        self.note.setProperty("role", "faint")
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.note)
        self.body.addStretch(1)

    # ------------------------------------------------------------------
    @property
    def month(self) -> str:
        return self.month_combo.current_month() or month_of(today())

    def refresh(self) -> None:
        month = self.month
        self.header.set_subtitle(
            f"{month_label(month)} · {t('看懂资产负债结构与消费习惯')}"
        )
        stats = self.service.repo.month_stats(month)
        worth = self.service.repo.net_worth()
        money = self.service.format

        self.income_card.set_value(
            money(stats.income), hint=t("工资、奖金等"), tone="income"
        )
        self.expense_card.set_value(
            money(stats.expense), hint=t("不含转账"), tone="expense"
        )
        self.net_card.set_value(
            money(stats.net),
            hint=t("收入 − 支出"),
            tone="income" if stats.net >= 0 else "expense",
        )
        self.rate_card.set_value(
            f"{stats.savings_rate:.1f}%",
            hint=t("结余 / 收入"),
            tone="income" if stats.savings_rate >= 20 else ("warning" if stats.savings_rate > 0 else "expense"),
        )

        self._refresh_worth(worth, money)
        breakdown = self.service.repo.category_breakdown(month, "expense")
        self._refresh_expense_pie(breakdown, stats.expense, money)
        self.trend_chart.set_data(self.service.repo.trend(12, end_month=month))
        self.category_bars.set_data(breakdown[:8], total=stats.expense)
        self._refresh_payees(month)

    def _refresh_worth(self, worth, money) -> None:
        total = worth.assets + worth.liabilities
        segments = [
            (t("存款 / 资产"), worth.assets, colors().primary),
            (t("负债"), worth.liabilities, colors().expense),
        ]
        self.worth_chart.set_data(
            segments,
            center_title=t("净资产"),
            center_value=money(worth.net),
            empty_text=t("暂无资产或负债"),
        )
        asset_pct = worth.assets / total * 100 if total else 0
        liability_pct = worth.liabilities / total * 100 if total else 0
        self.asset_legend.set_data(money(worth.assets), f"{asset_pct:.1f}%")
        self.liability_legend.set_data(money(worth.liabilities), f"{liability_pct:.1f}%")

    def _refresh_expense_pie(
        self, breakdown: list[CategorySpend], total: int, money
    ) -> None:
        if not breakdown:
            self.expense_chart.set_data(
                [], center_title=t("本月支出"), center_value=money(0)
            )
            self.expense_note.setText(t("本月还没有支出记录"))
            return
        top = breakdown[:6]
        segments = [
            (category_display(item.name), item.amount, item.color) for item in top
        ]
        rest = sum(item.amount for item in breakdown[6:])
        if rest:
            segments.append((t("其他"), rest, "#95A0B5"))
        self.expense_chart.set_data(
            segments,
            center_title=t("本月支出"),
            center_value=money(total),
            empty_text=t("暂无支出"),
        )
        top_name = breakdown[0]
        share = top_name.amount / total * 100 if total else 0
        self.expense_note.setText(
            t(
                "最大分类：{name} · {share}%",
                name=category_display(top_name.name),
                share=f"{share:.0f}",
            )
        )

    def _refresh_payees(self, month: str) -> None:
        clear_layout(self.payee_list)
        payees = self.service.repo.top_payees(month, limit=5)
        if not payees:
            self.payee_list.addWidget(
                EmptyState(
                    "search",
                    t("还没有消费对象"),
                    t("记账时填写“对方”，这里会自动汇总。"),
                )
            )
            return
        for index, payee in enumerate(payees, start=1):
            self.payee_list.addWidget(RankRow(index, payee, self.service))

    # ------------------------------------------------------------------ export
    def _export_menu(self) -> None:
        menu = QMenu(self)
        excel = QAction(t("导出 Excel"), menu)
        excel.triggered.connect(lambda: self._export("xlsx"))
        pdf = QAction(t("导出 PDF"), menu)
        pdf.triggered.connect(lambda: self._export("pdf"))
        menu.addAction(excel)
        menu.addAction(pdf)
        menu.exec(
            self.export_button.mapToGlobal(self.export_button.rect().bottomLeft())
        )

    def _export(self, kind: str) -> None:
        month = self.month_combo.current_month()
        if kind == "xlsx":
            default = report_filename()
            path, _ = QFileDialog.getSaveFileName(
                self, t("导出 Excel"), default, "Excel (*.xlsx)"
            )
        else:
            default = pdf_filename()
            path, _ = QFileDialog.getSaveFileName(
                self, t("导出 PDF"), default, "PDF (*.pdf)"
            )
        if not path:
            return
        try:
            if kind == "xlsx":
                export_excel(self.service.repo, path, month)
            else:
                export_pdf(self.service.repo, path, month)
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, t("导出失败"), str(exc), icon_name="alert")
            return
        self.window.notify(t("报表已导出：{name}", name=Path(path).name))
