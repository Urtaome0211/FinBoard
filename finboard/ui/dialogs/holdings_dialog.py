"""Holdings list and editor for investment accounts."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account, Holding
from ...core.money import format_cents, format_quantity, parse_quantity, parse_signed_amount
from ...core.service import FinanceService
from ...i18n import t
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
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：沪深300ETF、苹果"))
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText(t("可选，例如 510300、AAPL"))
        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText(t("例如：1000 或 12.5"))
        self.cost_input = QLineEdit()
        self.cost_input.setPlaceholderText(t("每股成本价"))
        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText(t("当前市价"))
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：长期持有"))

        form.addRow(form_label(t("名称")), self.name_input)
        form.addRow(form_label(t("代码")), self.symbol_input)
        form.addRow(form_label(t("数量")), self.quantity_input)
        form.addRow(form_label(t("成本价")), self.cost_input)
        form.addRow(form_label(t("现价")), self.price_input)
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

        for field in (self.quantity_input, self.cost_input, self.price_input):
            field.textChanged.connect(self._update_preview)
        self.name_input.setFocus()

        if holding:
            self.name_input.setText(holding.name)
            self.symbol_input.setText(holding.symbol)
            self.quantity_input.setText(format_quantity(holding.quantity_units))
            self.cost_input.setText(format_cents(holding.cost_price, ""))
            self.price_input.setText(format_cents(holding.price, ""))
            self.note_input.setText(holding.note)
        self._update_preview()

    def _values(self) -> tuple[int, int, int]:
        quantity = parse_quantity(self.quantity_input.text())
        cost = parse_signed_amount(self.cost_input.text(), allow_zero=True)
        price = parse_signed_amount(self.price_input.text(), allow_zero=True)
        if cost < 0 or price < 0:
            raise ValueError(t("成本价和现价不能为负数"))
        return quantity, cost, price

    def _update_preview(self) -> None:
        try:
            quantity, cost, price = self._values()
        except ValueError:
            self.preview.setText(t("填写数量、成本价与现价后显示市值和盈亏"))
            return
        cost_value = (quantity * cost + 500_000) // 1_000_000
        market = (quantity * price + 500_000) // 1_000_000
        profit = market - cost_value
        self.preview.setText(
            t("成本 {cost} · 市值 {value} · 浮动盈亏 {profit}").format(
                cost=self.service.format_money(cost_value, self.account.currency),
                value=self.service.format_money(market, self.account.currency),
                profit=self.service.format_money(profit, self.account.currency, plus=True),
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
        self.amount_input = QLineEdit()
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
        for label, widget in (
            (t("持仓成本"), self.cost_value),
            (t("当前市值"), self.market_value),
            (t("现金"), self.cash_value),
            (t("账户总值"), self.total_value),
            (t("浮动盈亏"), self.profit_value),
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
        self.sync_button = ThemedButton(t("按市值校准账户"), "soft", "refresh")
        self.sync_button.clicked.connect(self._sync)
        self.close_button = ThemedButton(t("关闭"), "secondary")
        self.close_button.clicked.connect(self.accept)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(self.cash_button)
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
        has_rows = bool(rows)
        self.table.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        self._selection_changed()


__all__ = ["CashDialog", "HoldingDialog", "HoldingsDialog"]
