"""Visual reports: net worth, spending mix, trends and rankings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import month_label, month_of, today
from ...core.exporters import export_excel, report_filename
from ...core.models import CategorySpend, PayeeSpend
from ...i18n import category_display, t
from ..charts import CategoryBars, DonutChart, SpendingCalendar, TrendChart
from ..pdf_export import export_pdf, export_range_pdf, pdf_filename
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
        self.fixed_button = ThemedButton("固定支出体检", "secondary", "target")
        self.fixed_button.clicked.connect(self._open_fixed_costs)
        header.add_action(self.fixed_button)
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

        self._build_range_card()

        self.portfolio_card = Card(padding=16, spacing=8)
        self.portfolio_card.add_header(
            "投资组合", "持仓市值、成本与累计收益"
        )
        portfolio_row = QHBoxLayout()
        portfolio_row.setSpacing(24)
        self.market_value = ValueLabel("", tone="primary", size=20, weight=700)
        self.cost_value = ValueLabel("", tone="text", size=20, weight=700)
        self.profit_value = ValueLabel("", tone="income", size=20, weight=700)
        self.dividend_value = ValueLabel("", tone="text", size=20, weight=700)
        for label, value in (
            ("持仓市值", self.market_value),
            ("持仓成本", self.cost_value),
            ("累计收益", self.profit_value),
            ("累计分红", self.dividend_value),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            title = QLabel(t(label))
            title.setProperty("role", "muted")
            column.addWidget(title)
            column.addWidget(value)
            portfolio_row.addLayout(column)
        portfolio_row.addStretch(1)
        self.portfolio_card.body.addLayout(portfolio_row)
        self.body.addWidget(self.portfolio_card)

        donuts = QHBoxLayout()
        donuts.setSpacing(18)
        self.worth_card = Card(padding=20, spacing=10)
        self.worth_card.add_header("资产与负债", "存款、投资、固定资产与欠款的比例")
        self.worth_chart = DonutChart()
        self.worth_chart.setMinimumHeight(220)
        self.worth_card.body.addWidget(self.worth_chart, 1)
        self.worth_legend = QVBoxLayout()
        self.worth_legend.setSpacing(8)
        self.asset_legend = LegendRow(colors().primary, "存款 / 资产")
        self.fixed_legend = LegendRow(colors().accent, "固定资产")
        self.liability_legend = LegendRow(colors().expense, "负债")
        self.worth_legend.addWidget(self.asset_legend)
        self.worth_legend.addWidget(self.fixed_legend)
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

        self.calendar_card = Card(padding=20, spacing=10)
        self.calendar_card.add_header("支出热力日历", "颜色越深，当天支出越多")
        self.calendar_chart = SpendingCalendar()
        self.calendar_card.body.addWidget(self.calendar_chart)
        self.body.addWidget(self.calendar_card)

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

        self.tag_card = Card(padding=20, spacing=10)
        self.tag_card.add_header("标签支出", "同一笔交易可以出现在多个标签下")
        self.tag_bars = CategoryBars()
        self.tag_card.body.addWidget(self.tag_bars)
        self.body.addWidget(self.tag_card)

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

        holdings = self.service.repo.holdings_summary()
        self.market_value.setText(money(holdings.market))
        self.cost_value.setText(money(holdings.cost))
        self.dividend_value.setText(money(holdings.dividends))
        self.profit_value.setText(
            self.service.format(holdings.total_profit, plus=holdings.total_profit > 0)
        )
        self.profit_value.set_tone(
            "income" if holdings.total_profit >= 0 else "expense"
        )

        self._refresh_worth(worth, money)
        breakdown = self.service.repo.category_breakdown(month, "expense")
        self._refresh_expense_pie(breakdown, stats.expense, money)
        self.trend_chart.set_data(self.service.repo.trend(12, end_month=month))
        self.calendar_chart.set_data(month, self.service.daily_expense(month))
        self.category_bars.set_data(breakdown[:8], total=stats.expense)
        tags = self.service.tag_breakdown(month)
        self.tag_card.setVisible(bool(tags))
        self.tag_bars.set_data(tags[:8], total=sum(item.amount for item in tags))
        self._refresh_payees(month)
        self._apply_range()

    def _build_range_card(self) -> None:
        self.range_card = Card(padding=16, spacing=10)
        self.range_card.add_header(
            "区间分析", "任意日期范围、同比环比与分类/标签/账户维度"
        )
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel(t("从")))
        self.range_start = QDateEdit(QDate(QDate.currentDate().year(), QDate.currentDate().month(), 1))
        self.range_start.setDisplayFormat("yyyy-MM-dd")
        self.range_start.setCalendarPopup(True)
        controls.addWidget(self.range_start)
        controls.addWidget(QLabel(t("到")))
        self.range_end = QDateEdit(QDate.currentDate())
        self.range_end.setDisplayFormat("yyyy-MM-dd")
        self.range_end.setCalendarPopup(True)
        controls.addWidget(self.range_end)
        self.range_preset = QComboBox()
        self.range_preset.setMinimumWidth(110)
        self._load_range_presets()
        controls.addWidget(self.range_preset)
        self.range_dimension = QComboBox()
        self.range_dimension.addItem(t("按分类"), "category")
        self.range_dimension.addItem(t("按标签"), "tag")
        self.range_dimension.addItem(t("按账户"), "account")
        controls.addWidget(self.range_dimension)
        apply_button = ThemedButton("查看区间", "primary", "search")
        apply_button.clicked.connect(lambda: self._apply_range())
        controls.addWidget(apply_button)
        save_button = ThemedButton("保存预设", "secondary", "save")
        save_button.clicked.connect(self._save_range_preset)
        controls.addWidget(save_button)
        self.range_export = ThemedButton("年度报告 PDF", "secondary", "download")
        self.range_export.clicked.connect(self._export_range_pdf)
        controls.addWidget(self.range_export)
        controls.addStretch(1)
        self.range_card.body.addLayout(controls)

        summary = QHBoxLayout()
        summary.setSpacing(20)
        self.range_income = ValueLabel("", tone="income", size=18, weight=700)
        self.range_expense = ValueLabel("", tone="expense", size=18, weight=700)
        self.range_net = ValueLabel("", tone="primary", size=18, weight=700)
        self.range_rate = ValueLabel("", tone="primary", size=18, weight=700)
        for title, value in (
            ("区间收入", self.range_income),
            ("区间支出", self.range_expense),
            ("区间结余", self.range_net),
            ("储蓄率", self.range_rate),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            label = QLabel(t(title))
            label.setProperty("role", "muted")
            column.addWidget(label)
            column.addWidget(value)
            summary.addLayout(column)
        summary.addStretch(1)
        self.range_card.body.addLayout(summary)

        self.range_compare = QLabel()
        self.range_compare.setProperty("role", "faint")
        self.range_compare.setWordWrap(True)
        self.range_card.body.addWidget(self.range_compare)
        self.range_bars = CategoryBars()
        self.range_card.body.addWidget(self.range_bars)
        self.body.addWidget(self.range_card)

        self.range_start.dateChanged.connect(lambda _value: self._mark_custom_range())
        self.range_end.dateChanged.connect(lambda _value: self._mark_custom_range())
        self.range_preset.currentIndexChanged.connect(self._range_preset_changed)
        self.range_dimension.currentIndexChanged.connect(lambda _index: self._apply_range())
        self._apply_range()

    def _range_dates(self) -> tuple[str, str]:
        return (
            self.range_start.date().toString("yyyy-MM-dd"),
            self.range_end.date().toString("yyyy-MM-dd"),
        )

    def _mark_custom_range(self) -> None:
        index = self.range_preset.findData("custom")
        if index >= 0:
            self.range_preset.blockSignals(True)
            self.range_preset.setCurrentIndex(index)
            self.range_preset.blockSignals(False)

    def _range_preset_changed(self, _index: int) -> None:
        key = self.range_preset.currentData()
        today = QDate.currentDate()
        if key == "month":
            start = QDate(today.year(), today.month(), 1)
            end = start.addMonths(1).addDays(-1)
        elif key == "last_month":
            start = QDate(today.year(), today.month(), 1).addMonths(-1)
            end = QDate(today.year(), today.month(), 1).addDays(-1)
        elif key == "3m":
            start = QDate(today.year(), today.month(), 1).addMonths(-2)
            end = today
        elif key == "year":
            start = QDate(today.year(), 1, 1)
            end = QDate(today.year(), 12, 31)
        elif isinstance(key, str) and key.startswith("saved:"):
            presets = self._saved_range_presets()
            item = next((p for p in presets if p.get("name") == key[6:]), None)
            if item is None:
                return
            start = QDate.fromString(item.get("start", ""), "yyyy-MM-dd")
            end = QDate.fromString(item.get("end", ""), "yyyy-MM-dd")
        else:
            return
        self.range_start.blockSignals(True)
        self.range_end.blockSignals(True)
        self.range_start.setDate(start)
        self.range_end.setDate(end)
        self.range_start.blockSignals(False)
        self.range_end.blockSignals(False)
        self._apply_range()

    def _apply_range(self) -> None:
        start, end = self._range_dates()
        dimension = self.range_dimension.currentData() or "category"
        try:
            report = self.service.range_report(start, end, dimension)
        except ValueError as exc:
            self.window.notify(str(exc))
            return
        money = self.service.format
        self.range_income.setText(money(report.income))
        self.range_expense.setText(money(report.expense))
        self.range_net.setText(money(report.net))
        self.range_net.set_tone("income" if report.net >= 0 else "expense")
        self.range_rate.setText(f"{report.savings_rate:.1f}%")
        parts = []
        for label, current, previous, year in (
            ("收入", report.income, report.previous_income, report.year_income),
            ("支出", report.expense, report.previous_expense, report.year_expense),
        ):
            chain = self._change_text(report.change(current, previous))
            yoy = self._change_text(report.change(current, year))
            parts.append(
                t(
                    "{label} 环比 {chain} · 同比 {yoy}",
                    label=t(label),
                    chain=chain,
                    yoy=yoy,
                )
            )
        self.range_compare.setText(" | ".join(parts))
        total = (
            sum(item.amount for item in report.breakdown)
            if dimension != "category"
            else report.expense
        )
        self.range_bars.set_data(report.breakdown[:8], total=max(1, total))

    @staticmethod
    def _change_text(value: float | None) -> str:
        return "—" if value is None else f"{value:+.1f}%"

    def _saved_range_presets(self) -> list[dict]:
        raw = self.window.settings.value("reports/range_presets", "[]")
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("name")]

    def _load_range_presets(self) -> None:
        self.range_preset.clear()
        self.range_preset.addItem(t("本月"), "month")
        self.range_preset.addItem(t("上月"), "last_month")
        self.range_preset.addItem(t("近 3 个月"), "3m")
        self.range_preset.addItem(t("今年"), "year")
        self.range_preset.addItem(t("自定义"), "custom")
        for preset in self._saved_range_presets():
            self.range_preset.addItem(preset["name"], f"saved:{preset['name']}")

    def _save_range_preset(self) -> None:
        name, ok = QInputDialog.getText(self, t("保存区间预设"), t("预设名称"))
        name = (name or "").strip()[:40]
        if not ok or not name:
            return
        start, end = self._range_dates()
        presets = [p for p in self._saved_range_presets() if p.get("name") != name]
        presets.append({"name": name, "start": start, "end": end})
        self.window.settings.setValue(
            "reports/range_presets", json.dumps(presets, ensure_ascii=False)
        )
        self.window.settings.sync()
        self._load_range_presets()
        self.range_preset.setCurrentIndex(self.range_preset.findData(f"saved:{name}"))

    def _export_range_pdf(self) -> None:
        end = self.range_end.date()
        start = QDate(end.year(), 1, 1)
        finish = QDate(end.year(), 12, 31)
        self.range_start.setDate(start)
        self.range_end.setDate(finish)
        self._apply_range()
        default = f"FinBoard-年度报告-{end.year()}.pdf"
        target, _ = QFileDialog.getSaveFileName(
            self, t("导出年度报告"), str(Path.home() / default), "PDF (*.pdf)"
        )
        if not target:
            return
        try:
            export_range_pdf(
                self.service.repo,
                target,
                start.toString("yyyy-MM-dd"),
                finish.toString("yyyy-MM-dd"),
                title=f"FinBoard 年度报告 {end.year()}",
            )
            self.window.notify(t("年度报告已导出"))
        except OSError as exc:
            ConfirmDialog.alert(self, t("导出失败"), str(exc))

    def _refresh_worth(self, worth, money) -> None:
        total = worth.assets + worth.liabilities
        segments = []
        if worth.account_assets > 0:
            segments.append((t("存款 / 资产"), worth.account_assets, colors().primary))
        if worth.fixed_assets > 0:
            segments.append((t("固定资产"), worth.fixed_assets, colors().accent))
        if worth.liabilities > 0:
            segments.append((t("负债"), worth.liabilities, colors().expense))
        self.worth_chart.set_data(
            segments,
            center_title=t("净资产"),
            center_value=money(worth.net),
            empty_text=t("暂无资产或负债"),
        )
        asset_pct = worth.account_assets / total * 100 if total else 0
        fixed_pct = worth.fixed_assets / total * 100 if total else 0
        liability_pct = worth.liabilities / total * 100 if total else 0
        self.asset_legend.set_data(money(worth.account_assets), f"{asset_pct:.1f}%")
        self.fixed_legend.set_data(money(worth.fixed_assets), f"{fixed_pct:.1f}%")
        self.fixed_legend.setVisible(worth.fixed_assets > 0)
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
    def _open_fixed_costs(self) -> None:
        from ..dialogs.fixed_cost import FixedCostDialog

        dialog = FixedCostDialog(self.service, self.window)
        dialog.exec()

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
