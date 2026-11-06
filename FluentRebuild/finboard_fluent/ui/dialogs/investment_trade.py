"""Investment trade entry and FIFO lot history."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account, Holding
from ...core.money import (
    format_cents,
    format_quantity,
    parse_amount,
    parse_quantity,
)
from ...core.service import FinanceService
from ...i18n import t
from ..theme import colors
from ..widgets import (
    EmptyState,
    SegmentedControl,
    ThemedButton,
    ValueLabel,
    divider,
)
from .common import dialog_footer, dialog_header, error_label, form_label, root_layout, show_error


class TradeDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        account: Account,
        *,
        kind: str = "buy",
        holding: Holding | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.holding = holding
        self.setWindowTitle(t("记录投资流水"))
        self.setMinimumWidth(520)
        root = root_layout(self)
        header, _ = dialog_header(
            t("记录投资流水"),
            f"{account.name} · {account.currency}",
            "investment",
        )
        root.addLayout(header)

        self.kind_control = SegmentedControl(
            [(t("买入"), "buy"), (t("卖出"), "sell"), (t("分红"), "dividend")],
            kind,
        )
        root.addWidget(self.kind_control)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(11)
        self.holding_combo = QComboBox()
        self.holding_combo.setMinimumWidth(300)
        for item in service.holdings(account.id):
            self.holding_combo.addItem(
                f"{item.name}{(' · ' + item.symbol) if item.symbol else ''} · "
                f"{format_quantity(item.quantity_units)}",
                item.id,
            )
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：沪深300ETF、苹果"))
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText(t("可选，例如 510300、AAPL"))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setCalendarPopup(True)
        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText(t("例如：1000 或 12.5"))
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText(t("每股价格"))
        self.fee_input = QLineEdit()
        self.fee_input.setPlaceholderText(t("可选，买卖手续费"))
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText(t("现金分红金额"))
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注"))

        form.addRow(form_label(t("持仓")), self.holding_combo)
        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("代码")), self.symbol_input)
        form.addRow(form_label(t("日期")), self.date_edit)
        form.addRow(form_label(t("数量")), self.quantity_input)
        form.addRow(form_label(t("价格")), self.price_input)
        form.addRow(form_label(t("手续费")), self.fee_input)
        form.addRow(form_label(t("分红金额")), self.amount_input)
        form.addRow(form_label(t("备注")), self.note_input)
        root.addLayout(form)

        self.preview = QLabel()
        self.preview.setProperty("role", "muted")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("保存流水"), cancel_text=t("取消")
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)

        self.kind_control.changed.connect(self._kind_changed)
        self.holding_combo.currentIndexChanged.connect(self._holding_changed)
        for field in (self.quantity_input, self.price_input, self.fee_input, self.amount_input):
            field.textChanged.connect(self._update_preview)
        if holding is not None:
            self._select_holding(holding)
        elif self.holding_combo.count():
            self.holding_combo.setCurrentIndex(0)
            self._holding_changed()
        self._kind_changed(kind)

    def _select_holding(self, holding: Holding) -> None:
        for index in range(self.holding_combo.count()):
            if self.holding_combo.itemData(index) == holding.id:
                self.holding_combo.setCurrentIndex(index)
                return

    def _holding_changed(self) -> None:
        holding_id = self.holding_combo.currentData()
        if holding_id is None:
            return
        for item in self.service.holdings(self.account.id):
            if item.id == holding_id:
                self.name_input.setText(item.name)
                self.symbol_input.setText(item.symbol)
                if item.price:
                    self.price_input.setText(f"{item.price / 100:.2f}")
                if not self.quantity_input.text().strip():
                    self.quantity_input.setText(format_quantity(item.quantity_units))
                break
        self._update_preview()

    def _kind_changed(self, kind: object) -> None:
        kind = str(kind)
        is_trade = kind in ("buy", "sell")
        self.quantity_input.setEnabled(is_trade)
        self.price_input.setEnabled(is_trade)
        self.fee_input.setEnabled(is_trade)
        self.amount_input.setEnabled(kind == "dividend")
        self.holding_combo.setEnabled(kind == "sell")
        self.holding_combo.setVisible(kind == "sell")
        if kind == "sell" and self.holding_combo.count() == 0:
            self.preview.setText(t("当前没有可卖出的持仓"))
        else:
            self._update_preview()

    def _update_preview(self) -> None:
        kind = str(self.kind_control.value())
        try:
            if kind == "dividend":
                amount = parse_amount(self.amount_input.text())
                self.preview.setText(t("分红 {amount}", amount=self.service.format_money(amount, self.account.currency)))
                return
            quantity = parse_quantity(self.quantity_input.text())
            price = parse_amount(self.price_input.text())
            fee = parse_amount(self.fee_input.text()) if self.fee_input.text().strip() else 0
            gross = (quantity * price + 500_000) // 1_000_000
            net = gross + fee if kind == "buy" else gross - fee
            self.preview.setText(
                t(
                    "成交金额 {gross} · 手续费 {fee} · 净额 {net}",
                    gross=self.service.format_money(gross, self.account.currency),
                    fee=self.service.format_money(fee, self.account.currency),
                    net=self.service.format_money(net, self.account.currency),
                )
            )
        except ValueError:
            self.preview.setText(t("填写数量与价格后显示成交金额"))

    def _save(self) -> None:
        kind = str(self.kind_control.value())
        try:
            if kind == "sell":
                holding_id = self.holding_combo.currentData()
                holding = next(
                    (item for item in self.service.holdings(self.account.id) if item.id == holding_id),
                    None,
                )
                if holding is None:
                    raise ValueError(t("请选择要卖出的持仓"))
                symbol, name = holding.symbol, holding.name
                quantity = parse_quantity(self.quantity_input.text())
                price = parse_amount(self.price_input.text())
                fee = parse_amount(self.fee_input.text()) if self.fee_input.text().strip() else 0
                self.service.record_investment_trade(
                    self.account.id,
                    kind="sell",
                    symbol=symbol,
                    name=name,
                    trade_date=self.date_edit.date().toString("yyyy-MM-dd"),
                    quantity_units=quantity,
                    price=price,
                    fee=fee,
                    note=self.note_input.text(),
                )
            elif kind == "buy":
                if not self.name_input.text().strip():
                    raise ValueError(t("请填写持仓名称"))
                quantity = parse_quantity(self.quantity_input.text())
                price = parse_amount(self.price_input.text())
                fee = parse_amount(self.fee_input.text()) if self.fee_input.text().strip() else 0
                self.service.record_investment_trade(
                    self.account.id,
                    kind="buy",
                    symbol=self.symbol_input.text(),
                    name=self.name_input.text(),
                    trade_date=self.date_edit.date().toString("yyyy-MM-dd"),
                    quantity_units=quantity,
                    price=price,
                    fee=fee,
                    note=self.note_input.text(),
                )
            else:
                amount = parse_amount(self.amount_input.text())
                self.service.record_investment_trade(
                    self.account.id,
                    kind="dividend",
                    symbol=self.symbol_input.text(),
                    name=self.name_input.text() or t("现金分红"),
                    trade_date=self.date_edit.date().toString("yyyy-MM-dd"),
                    amount=amount,
                    note=self.note_input.text(),
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()


class InvestmentTradesDialog(QDialog):
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
        self.setWindowTitle(t("投资流水"))
        self.resize(980, 720)
        root = root_layout(self)
        header, _ = dialog_header(
            t("投资流水"),
            t("逐笔买卖按 FIFO 计算成本，持仓由流水汇总"),
            "investment",
        )
        root.addLayout(header)

        summary = QWidget()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setSpacing(24)
        self.cost_value = ValueLabel("", size=18, weight=700)
        self.market_value = ValueLabel("", size=18, weight=700)
        self.realized_value = ValueLabel("", size=18, weight=700)
        self.dividend_value = ValueLabel("", size=18, weight=700)
        for label, widget in (
            (t("持仓成本"), self.cost_value),
            (t("当前市值"), self.market_value),
            (t("已实现盈亏"), self.realized_value),
            (t("累计分红"), self.dividend_value),
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

        root.addWidget(self._section_title(t("流水")))
        self.trades_table = self._make_table(
            [t("日期"), t("类型"), t("名称"), t("数量"), t("价格"), t("手续费"), t("金额"), t("净额")]
        )
        root.addWidget(self.trades_table, 1)

        root.addWidget(self._section_title(t("FIFO 批次")))
        self.lots_table = self._make_table(
            [t("买入日期"), t("名称"), t("原始数量"), t("剩余数量"), t("单位成本"), t("剩余成本")]
        )
        root.addWidget(self.lots_table, 1)

        self.empty = EmptyState(
            "investment",
            t("还没有投资流水"),
            t("记录第一笔买入，之后卖出会自动按 FIFO 结转成本"),
            t("买入"),
            lambda: self._add("buy"),
        )
        root.addWidget(self.empty)

        actions = QHBoxLayout()
        self.buy_button = ThemedButton(t("买入"), "primary", "plus")
        self.buy_button.clicked.connect(lambda: self._add("buy"))
        self.sell_button = ThemedButton(t("卖出"), "secondary", "minus")
        self.sell_button.clicked.connect(lambda: self._add("sell"))
        self.dividend_button = ThemedButton(t("分红"), "secondary", "income")
        self.dividend_button.clicked.connect(lambda: self._add("dividend"))
        close_button = ThemedButton(t("关闭"), "secondary")
        close_button.clicked.connect(self.accept)
        actions.addWidget(self.buy_button)
        actions.addWidget(self.sell_button)
        actions.addWidget(self.dividend_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self.service.changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "cardTitle")
        return label

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setShowGrid(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in range(3, len(headers)):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        table.setMinimumHeight(180)
        return table

    def _add(self, kind: str) -> None:
        dialog = TradeDialog(self.service, self.account, kind=kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def refresh(self) -> None:
        trades = self.service.investment_trades(self.account.id)
        lots = [item for item in self.service.investment_lots(self.account.id) if item.remaining_units > 0]
        summary = self.service.holdings_summary(self.account.id)
        self.cost_value.setText(self.service.format_money(summary.cost, self.account.currency))
        self.market_value.setText(self.service.format_money(summary.market, self.account.currency))
        self.realized_value.setText(self.service.format_money(summary.realized, self.account.currency))
        self.dividend_value.setText(self.service.format_money(summary.dividends, self.account.currency))
        self.empty.setVisible(not trades)
        self.trades_table.setVisible(bool(trades))
        self.lots_table.setVisible(bool(lots))
        self.trades_table.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            values = [
                trade.trade_date,
                t(trade.label),
                f"{trade.name}{(' · ' + trade.symbol) if trade.symbol else ''}",
                format_quantity(trade.quantity_units),
                self.service.format_money(trade.price, trade.currency) if trade.price else "—",
                self.service.format_money(trade.fee, trade.currency) if trade.fee else "—",
                self.service.format_money(trade.amount, trade.currency) if trade.amount else "—",
                self.service.format_money(trade.net_value, trade.currency),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (3, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.trades_table.setItem(row, column, item)
        self.lots_table.setRowCount(len(lots))
        for row, lot in enumerate(lots):
            values = [
                lot.acquired_date,
                f"{lot.name}{(' · ' + lot.symbol) if lot.symbol else ''}",
                format_quantity(lot.quantity_units),
                format_quantity(lot.remaining_units),
                self.service.format_money(lot.unit_cost, lot.currency),
                self.service.format_money(lot.cost_value, lot.currency),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.lots_table.setItem(row, column, item)
