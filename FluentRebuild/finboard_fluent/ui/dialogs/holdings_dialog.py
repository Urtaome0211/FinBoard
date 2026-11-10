"""Holdings list and editor for investment accounts."""

from __future__ import annotations
from ..fluent_controls import LineEdit

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account, Holding
from ...core.money import format_cents, format_quantity, parse_quantity, parse_signed_amount
from ...core.quotes import QuoteError
from ...core.service import FinanceService
from ...i18n import t
from ..charts import DonutChart
from ..models import HoldingTableModel
from ..theme import colors
from ..widgets import (
    ConfirmDialog,
    EmptyState,
    IconButton,
    PageHeader,
    ThemedButton,
    ValueLabel,
    divider,
    icon_label,
    set_error,
)
from .common import dialog_footer, dialog_header, error_label, form_label, root_layout, show_error
from .investment_trade import InvestmentTradesDialog


class HoldingDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        account: Account,
        holding: Holding | None = None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.holding = holding
        self.setWindowTitle(t("编辑持仓") if holding else t("新建持仓"))
        self.setMinimumWidth(500)
        root = root_layout(self)
        header, _ = dialog_header(
            t("编辑持仓") if holding else t("新建持仓"),
            f"{account.name} · {account.currency}",
            "investment",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.name_input = LineEdit()
        self.name_input.setPlaceholderText(t("例如：沪深300ETF、苹果"))
        self.symbol_input = LineEdit()
        self.symbol_input.setPlaceholderText(t("可选，例如 510300、AAPL"))
        self.quantity_input = LineEdit()
        self.quantity_input.setPlaceholderText(t("例如：1000 或 12.5"))
        self.cost_input = LineEdit()
        self.cost_input.setPlaceholderText(t("每股成本价"))
        self.price_input = LineEdit()
        self.price_input.setPlaceholderText(t("当前市价"))
        self.realized_input = LineEdit()
        self.realized_input.setPlaceholderText(t("卖出后的累计已实现收益，可为负"))
        self.dividends_input = LineEdit()
        self.dividends_input.setPlaceholderText(t("累计收到的现金分红"))
        self.note_input = LineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：长期持有"))
        self.asset_class_input = LineEdit()
        self.asset_class_input.setPlaceholderText(t("例如：股票、债券、现金、另类"))
        self.region_input = LineEdit()
        self.region_input.setPlaceholderText(t("例如：中国、美国、全球"))

        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("代码")), self.symbol_input)
        form.addRow(form_label(t("数量")), self.quantity_input)
        form.addRow(form_label(t("成本价")), self.cost_input)
        form.addRow(form_label(t("现价")), self.price_input)
        form.addRow(form_label(t("已实现收益")), self.realized_input)
        form.addRow(form_label(t("累计分红")), self.dividends_input)
        form.addRow(form_label(t("资产类别")), self.asset_class_input)
        form.addRow(form_label(t("地区")), self.region_input)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setProperty("role", "muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.error = error_label()
        root.addWidget(self.error)
        root.addStretch(1)
        footer = dialog_footer(
            self, self.error, save_text=t("保存持仓"), cancel_text=t("取消")
        )
        save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button = save_button
        save_button.clicked.connect(self._save)
        root.addLayout(footer)

        for field in (
            self.quantity_input,
            self.cost_input,
            self.price_input,
            self.realized_input,
            self.dividends_input,
        ):
            field.textChanged.connect(self._update_preview)
        self.name_input.setFocus()

        if holding:
            self.name_input.setText(holding.name)
            self.symbol_input.setText(holding.symbol)
            self.quantity_input.setText(format_quantity(holding.quantity_units))
            self.cost_input.setText(format_cents(holding.cost_price, ""))
            self.price_input.setText(format_cents(holding.price, ""))
            self.realized_input.setText(format_cents(holding.realized_profit, ""))
            self.dividends_input.setText(format_cents(holding.dividends, ""))
            self.note_input.setText(holding.note)
            self.asset_class_input.setText(holding.asset_class)
            self.region_input.setText(holding.region)
        self._update_preview()

    def _values(self) -> tuple[int, int, int]:
        quantity = parse_quantity(self.quantity_input.text())
        cost = parse_signed_amount(self.cost_input.text(), allow_zero=True)
        price = parse_signed_amount(self.price_input.text(), allow_zero=True)
        if cost < 0 or price < 0:
            raise ValueError(t("成本价和现价不能为负数"))
        return quantity, cost, price

    def _return_values(self) -> tuple[int, int]:
        realized = parse_signed_amount(
            self.realized_input.text().strip() or "0", allow_zero=True
        )
        dividends = parse_signed_amount(
            self.dividends_input.text().strip() or "0", allow_zero=True
        )
        if dividends < 0:
            raise ValueError(t("累计分红不能为负数"))
        return realized, dividends

    def _update_preview(self) -> None:
        try:
            quantity, cost, price = self._values()
            realized, dividends = self._return_values()
        except ValueError:
            self.preview.setText(t("填写数量、成本价与现价后显示市值和盈亏"))
            return
        cost_value = (quantity * cost + 500_000) // 1_000_000
        market = (quantity * price + 500_000) // 1_000_000
        profit = market - cost_value
        total = profit + realized + dividends
        self.preview.setText(
            t("成本 {cost} · 市值 {value} · 浮动盈亏 {profit} · 累计收益 {total}").format(
                cost=self.service.format_money(cost_value, self.account.currency),
                value=self.service.format_money(market, self.account.currency),
                profit=self.service.format_money(profit, self.account.currency, plus=True),
                total=self.service.format_money(total, self.account.currency, plus=True),
            )
        )

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, t("请输入持仓名称"))
            self.name_input.setFocus()
            return
        try:
            quantity, cost, price = self._values()
            realized, dividends = self._return_values()
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        try:
            if self.holding:
                self.service.update_holding(
                    self.holding.id,
                    account_id=self.account.id,
                    name=name,
                    symbol=self.symbol_input.text().strip(),
                    quantity_units=quantity,
                    cost_price=cost,
                    price=price,
                    note=self.note_input.text().strip(),
                    realized_profit=realized,
                    dividends=dividends,
                    asset_class=self.asset_class_input.text().strip(),
                    region=self.region_input.text().strip(),
                )
            else:
                self.service.add_holding(
                    self.account.id,
                    name,
                    symbol=self.symbol_input.text().strip(),
                    quantity_units=quantity,
                    cost_price=cost,
                    price=price,
                    note=self.note_input.text().strip(),
                    realized_profit=realized,
                    dividends=dividends,
                    asset_class=self.asset_class_input.text().strip(),
                    region=self.region_input.text().strip(),
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


class CashDialog(QDialog):
    """Edit the uninvested cash portion of an investment account."""

    def __init__(
        self,
        service: FinanceService,
        account: Account,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.setWindowTitle(t("调整现金"))
        self.setMinimumWidth(460)
        root = root_layout(self)
        header, _ = dialog_header(
            t("调整现金"),
            f"{account.name} · {t('与持仓分开记录，不计入成本')}",
            "cash",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.amount_input = LineEdit()
        self.amount_input.setObjectName("AmountInput")
        self.amount_input.setPlaceholderText("0.00")
        self.amount_input.setText(format_cents(account.cash_balance, ""))
        form.addRow(form_label(t("现金余额")), self.amount_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setProperty("role", "muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.amount_input.textChanged.connect(self._update_preview)

        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("保存现金"), cancel_text=t("取消")
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)
        self.amount_input.setFocus()
        self.amount_input.selectAll()
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            cash = parse_signed_amount(self.amount_input.text(), allow_zero=True)
            if cash < 0:
                raise ValueError
            holdings = self.account.holdings_value
            total = cash + holdings
            self.preview.setText(
                t("现金 {cash} + 持仓 {holdings} = 账户总值 {total}").format(
                    cash=self.service.format_money(cash, self.account.currency),
                    holdings=self.service.format_money(holdings, self.account.currency),
                    total=self.service.format_money(total, self.account.currency),
                )
            )
            set_error(self.amount_input, False)
        except (ValueError, ArithmeticError):
            self.preview.setText(t("输入现金余额后显示账户总值"))
            set_error(self.amount_input, bool(self.amount_input.text().strip()))

    def _save(self) -> None:
        try:
            cash = parse_signed_amount(self.amount_input.text(), allow_zero=True)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        if cash < 0:
            show_error(self.error, t("现金余额不能为负数"))
            return
        try:
            self.service.set_cash_balance(self.account.id, cash)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


class HoldingsDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        account: Account,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.setWindowTitle(t("持仓与成本"))
        self.resize(860, 620)
        root = root_layout(self)
        header, _ = dialog_header(
            t("持仓与成本"),
            f"{account.name} · {t('成本、市值与浮动盈亏')}",
            "investment",
        )
        root.addLayout(header)

        summary = QWidget()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setSpacing(24)
        self.cost_value = ValueLabel("", size=18, weight=700)
        self.market_value = ValueLabel("", size=18, weight=700)
        self.cash_value = ValueLabel("", size=18, weight=700)
        self.total_value = ValueLabel("", size=18, weight=700)
        self.profit_value = ValueLabel("", size=18, weight=700)
        self.total_profit_value = ValueLabel("", size=18, weight=700)
        self.xirr_value = ValueLabel("", size=18, weight=700)
        for label, widget in (
            (t("持仓成本"), self.cost_value),
            (t("当前市值"), self.market_value),
            (t("现金"), self.cash_value),
            (t("账户总值"), self.total_value),
            (t("浮动盈亏"), self.profit_value),
            (t("累计收益"), self.total_profit_value),
            (t("年化 XIRR"), self.xirr_value),
        ):
            column = QVBoxLayout()
            column.setSpacing(2)
            caption = QLabel(label)
            caption.setProperty("role", "muted")
            column.addWidget(caption)
            column.addWidget(widget)
            summary_layout.addLayout(column)
        summary_layout.addStretch(1)
        summary.setObjectName("SoftCard")
        root.addWidget(summary)

        allocation_row = QHBoxLayout()
        allocation_row.setSpacing(16)
        self.allocation_chart = DonutChart()
        self.allocation_chart.setMinimumSize(150, 150)
        self.allocation_chart.setMaximumWidth(190)
        allocation_row.addWidget(self.allocation_chart)
        self.allocation_legend = QVBoxLayout()
        self.allocation_legend.setSpacing(4)
        allocation_row.addLayout(self.allocation_legend, 1)
        root.addLayout(allocation_row)

        self.table = QTableView()
        self.model = HoldingTableModel(service, self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.doubleClicked.connect(lambda _index: self._edit())
        for index, width in enumerate((150, 90, 100, 100, 100, 120, 120, 90)):
            self.table.setColumnWidth(index, width)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.empty = EmptyState(
            "investment",
            t("还没有持仓"),
            t("添加股票、基金或 ETF，查看成本与浮动盈亏"),
            t("添加持仓"),
            self._add,
        )
        root.addWidget(self.empty)

        self.quote_label = QLabel()
        self.quote_label.setProperty("role", "muted")
        self.quote_label.setWordWrap(True)
        root.addWidget(self.quote_label)

        self.error = error_label()
        root.addWidget(self.error)
        actions = QHBoxLayout()
        self.add_button = ThemedButton(t("添加持仓"), "primary", "plus")
        self.add_button.clicked.connect(self._add)
        self.edit_button = ThemedButton(t("编辑"), "secondary", "edit")
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = ThemedButton(t("删除"), "ghost", "trash")
        self.delete_button.clicked.connect(self._delete)
        self.cash_button = ThemedButton(t("调整现金"), "secondary", "wallet")
        self.cash_button.clicked.connect(self._adjust_cash)
        self.trades_button = ThemedButton(t("投资流水"), "secondary", "list")
        self.quote_button = ThemedButton(t("更新行情"), "secondary", "refresh")
        self.sync_button = ThemedButton(t("按市值校准账户"), "soft", "refresh")
        self.quote_button.clicked.connect(self._refresh_quotes)
        self.sync_button.clicked.connect(self._sync)
        self.trades_button.clicked.connect(self._open_trades)
        self.close_button = ThemedButton(t("关闭"), "secondary")
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(self.cash_button)
        actions.addWidget(self.trades_button)
        actions.addWidget(self.quote_button)
        actions.addWidget(self.sync_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.service.changed.connect(self.refresh)
        self.refresh()

    def _selection_changed(self) -> None:
        self.edit_button.setEnabled(self._selected() is not None)
        self.delete_button.setEnabled(self._selected() is not None)
        self.sync_button.setEnabled(bool(self.model.rowCount()))

    def _selected(self) -> Holding | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.holding_at(rows[0].row())

    def _add(self) -> None:
        dialog = HoldingDialog(self.service, self.account, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _edit(self) -> None:
        holding = self._selected()
        if not holding:
            return
        dialog = HoldingDialog(self.service, self.account, holding, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _delete(self) -> None:
        holding = self._selected()
        if not holding:
            return
        if not ConfirmDialog.confirm(
            self,
            t("删除持仓"),
            t("确定删除「{name}」？").format(name=holding.name),
            danger=True,
        ):
            return
        self.service.delete_holding(holding.id)
        self.refresh()

    def _adjust_cash(self) -> None:
        account = self.service.repo.get_account(self.account.id)
        dialog = CashDialog(self.service, account, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _open_trades(self) -> None:
        dialog = InvestmentTradesDialog(self.service, self.account, parent=self)
        dialog.exec()
        self.refresh()

    def _refresh_quotes(self) -> None:
        try:
            quotes = self.service.refresh_quotes()
        except QuoteError as exc:
            ConfirmDialog.alert(self, t("行情更新失败"), str(exc))
            return
        except Exception as exc:
            ConfirmDialog.alert(self, t("行情更新失败"), str(exc))
            return
        self.refresh()
        if quotes:
            window = self.parent()
            if hasattr(window, "notify"):
                window.notify(t("已更新 {count} 个行情", count=len(quotes)))
        else:
            ConfirmDialog.alert(self, t("没有可更新的行情"), t("请先为持仓填写股票或基金代码。"))

    def _sync(self) -> None:
        try:
            self.service.sync_holdings_value(self.account.id)
        except ValueError as exc:
            ConfirmDialog.alert(self, t("无法校准"), str(exc))
            return
        self.refresh()

    def refresh(self) -> None:
        self.account = self.service.repo.get_account(self.account.id)
        rows = self.service.holdings(self.account.id)
        self.model.set_holdings(rows)
        summary = self.service.holdings_summary(self.account.id)
        symbol = self.account.currency
        self.cost_value.setText(self.service.format_money(summary.cost, symbol))
        self.market_value.setText(self.service.format_money(summary.market, symbol))
        self.cash_value.setText(
            self.service.format_money(self.account.cash_balance, symbol)
        )
        self.total_value.setText(
            self.service.format_money(self.account.balance, symbol)
        )
        self.profit_value.setText(
            self.service.format_money(summary.profit, symbol, plus=True)
        )
        self.profit_value.set_tone(
            "income" if summary.profit > 0 else "expense" if summary.profit < 0 else "muted"
        )
        self.total_profit_value.setText(
            self.service.format_money(summary.total_profit, symbol, plus=True)
        )
        self.total_profit_value.set_tone(
            "income"
            if summary.total_profit > 0
            else "expense"
            if summary.total_profit < 0
            else "muted"
        )
        self.total_profit_value.setToolTip(
            t("浮动盈亏 {profit} · 已实现 {realized} · 分红 {dividends}").format(
                profit=self.service.format_money(summary.profit, symbol),
                realized=self.service.format_money(summary.realized, symbol),
                dividends=self.service.format_money(summary.dividends, symbol),
            )
        )
        self._update_allocation(rows, symbol)
        quotes, fetched_at = self.service.quote_cache()
        if fetched_at:
            self.quote_label.setText(
                t(
                    "行情更新于 {time} · {count} 个代码（腾讯行情）",
                    time=fetched_at[:16].replace("T", " "),
                    count=len(quotes),
                )
            )
        else:
            self.quote_label.setText(t("尚未更新行情；可手动更新或到设置中开启自动更新"))
        rate = self.service.portfolio_xirr(self.account.id)
        self.xirr_value.setText(
            "—" if rate is None else f"{rate * 100:.2f}%"
        )
        self.xirr_value.set_tone(
            "income"
            if rate is not None and rate > 0
            else "expense"
            if rate is not None and rate < 0
            else "muted"
        )
        self.xirr_value.setToolTip(
            t("基于持仓成本、当前市值和创建日期估算；历史不足时显示 —")
        )
        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        self._selection_changed()

    def _update_allocation(self, rows: list[Holding], symbol: str) -> None:
        while self.allocation_legend.count():
            item = self.allocation_legend.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not rows:
            self.allocation_chart.set_data([], center_title=t("持仓市值"))
            return
        use_class = any(item.asset_class.strip() for item in rows)
        grouped: dict[str, int] = {}
        for item in rows:
            key = item.asset_class.strip() if use_class else item.name
            if not key:
                key = t("未分类")
            grouped[key] = grouped.get(key, 0) + item.market_value
        ordered = sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)
        palette = colors()
        swatches = [
            palette.primary,
            palette.info,
            palette.income,
            palette.warning,
            palette.accent,
            palette.expense,
            palette.muted,
        ]
        top = ordered[:6]
        if len(ordered) > 6:
            top.append((t("其他"), sum(value for _, value in ordered[6:])))
        total = sum(value for _, value in top) or 1
        segments = [
            (label, value, swatches[index % len(swatches)])
            for index, (label, value) in enumerate(top)
        ]
        self.allocation_chart.set_data(
            segments,
            center_title=t("持仓市值"),
            center_value=self.service.format_money(total, symbol),
        )
        for label, value, color in segments:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color};")
            text = QLabel(f"{label}  {value / total * 100:.1f}%")
            text.setProperty("role", "muted")
            line = QHBoxLayout()
            line.setSpacing(6)
            line.addWidget(dot)
            line.addWidget(text, 1)
            line.addStretch(1)
            holder = QWidget()
            holder.setLayout(line)
            self.allocation_legend.addWidget(holder)


__all__ = ["CashDialog", "HoldingDialog", "HoldingsDialog"]
