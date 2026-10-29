"""Record daily market values for an investment account."""

from __future__ import annotations

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Account, AccountValuation
from ...core.money import (
    CURRENCIES,
    format_cents,
    format_percentage,
    parse_signed_amount,
    percentage,
)
from ...core.service import FinanceService
from ..charts import ValuationChart
from ..theme import colors
from ..widgets import (
    Card,
    ConfirmDialog,
    IconButton,
    ValueLabel,
    clear_layout,
)
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class _HistoryRow(QFrame):
    delete_requested = Signal(int)

    def __init__(self, valuation: AccountValuation, symbol: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ListRow")
        self.valuation = valuation
        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(10)

        date = QLabel(valuation.date)
        date.setProperty("role", "muted")
        date.setFixedWidth(92)
        layout.addWidget(date)

        value = ValueLabel(format_cents(valuation.value, symbol), size=13, weight=600)
        value.setFixedWidth(130)
        layout.addWidget(value)

        note = QLabel(valuation.note or "—")
        note.setProperty("role", "faint")
        note.setToolTip(valuation.note)
        layout.addWidget(note, 1)

        remove = IconButton("trash", "删除这条市值记录", color=colors().faint, size=16)
        remove.clicked.connect(
            lambda _checked=False: self.delete_requested.emit(self.valuation.id)
        )
        layout.addWidget(remove)


class ValuationDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        account: Account,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.account = account
        self.symbol = CURRENCIES.get(account.currency, CURRENCIES["CNY"])["symbol"]
        self.setWindowTitle(f"市值记录 · {account.name}")
        self.setModal(True)
        self.setMinimumSize(720, 600)
        self.resize(760, 700)
        self.setSizeGripEnabled(False)

        layout = root_layout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        header, _ = dialog_header(
            "市值记录",
            f"{account.name} · {account.currency} · 记录每日收盘市值",
            "chart",
        )
        layout.addLayout(header)

        summary = QFrame()
        summary.setObjectName("SoftCard")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(24)

        latest_box = QVBoxLayout()
        latest_box.setSpacing(2)
        latest_title = QLabel("最新市值")
        latest_title.setProperty("role", "faint")
        self.latest_value = ValueLabel("—", size=22, weight=700)
        latest_box.addWidget(latest_title)
        latest_box.addWidget(self.latest_value)
        summary_layout.addLayout(latest_box)

        change_box = QVBoxLayout()
        change_box.setSpacing(2)
        change_title = QLabel("较上次")
        change_title.setProperty("role", "faint")
        self.change_value = ValueLabel("—", size=16, weight=600)
        change_box.addWidget(change_title)
        change_box.addWidget(self.change_value)
        summary_layout.addLayout(change_box)

        balance_box = QVBoxLayout()
        balance_box.setSpacing(2)
        balance_title = QLabel("当前余额")
        balance_title.setProperty("role", "faint")
        self.balance_value = ValueLabel(format_cents(account.balance, self.symbol), size=16, weight=600)
        balance_box.addWidget(balance_title)
        balance_box.addWidget(self.balance_value)
        summary_layout.addLayout(balance_box)
        summary_layout.addStretch(1)
        layout.addWidget(summary)

        form_row = QHBoxLayout()
        form_row.setSpacing(12)
        form_row.addWidget(form_label("日期"))
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setMaximumDate(QDate.currentDate())
        self.date_input.setFixedWidth(142)
        form_row.addWidget(self.date_input)
        form_row.addSpacing(8)
        form_row.addWidget(form_label("市值"))
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("今日收盘总市值")
        self.amount_input.setMaxLength(20)
        self.amount_input.setMinimumWidth(150)
        form_row.addWidget(QLabel(self.symbol))
        form_row.addWidget(self.amount_input, 1)
        layout.addLayout(form_row)

        note_row = QHBoxLayout()
        note_row.setSpacing(12)
        note_row.addWidget(form_label("备注"))
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("可选，例如：月末收盘 / 转入资金")
        self.note_input.setMaxLength(120)
        note_row.addWidget(self.note_input, 1)
        layout.addLayout(note_row)

        self.error = error_label()
        layout.addWidget(self.error)

        chart_card = Card(padding=16, spacing=8)
        chart_card.body.addWidget(self._card_title("市值走势", "按记录日期升序"))
        self.chart = ValuationChart()
        self.chart.setMinimumHeight(180)
        chart_card.body.addWidget(self.chart, 1)
        layout.addWidget(chart_card, 1)

        history_card = Card(padding=16, spacing=8)
        history_card.body.addWidget(self._card_title("历史记录", "同日重复保存会覆盖原值"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(122)
        holder = QWidget()
        self.history_layout = QVBoxLayout(holder)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(0)
        scroll.setWidget(holder)
        history_card.body.addWidget(scroll)
        layout.addWidget(history_card)

        footer = dialog_footer(self, self.error, save_text="保存市值", cancel_text="关闭")
        save = footer.itemAt(footer.count() - 1).widget()
        save.clicked.connect(self._save)
        layout.addLayout(footer)

        self.amount_input.returnPressed.connect(self._save)
        self._refresh()

    @staticmethod
    def _card_title(title: str, hint: str = "") -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = QLabel(title)
        label.setProperty("role", "cardTitle")
        row.addWidget(label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "faint")
            row.addWidget(hint_label)
        row.addStretch(1)
        return box

    def _refresh(self) -> None:
        self.account = self.service.repo.get_account(
            self.account.id, include_archived=True
        )
        valuations = self.service.valuations(self.account.id)
        self.chart.set_data(valuations, self.symbol)
        if valuations:
            latest = valuations[0]
            self.latest_value.setText(format_cents(latest.value, self.symbol))
            if len(valuations) > 1:
                previous = valuations[1]
                delta = latest.value - previous.value
                if previous.value:
                    pct = percentage(delta, previous.value)
                    self.change_value.setText(
                        f"{format_cents(delta, self.symbol, plus=True)} ({format_percentage(delta, previous.value)})"
                    )
                else:
                    self.change_value.setText(format_cents(delta, self.symbol, plus=True))
                self.change_value.set_tone("income" if delta >= 0 else "expense")
            else:
                self.change_value.setText("首次记录")
                self.change_value.set_tone("muted")
            self.balance_value.setText(format_cents(self.account.balance, self.symbol))
        else:
            self.latest_value.setText("—")
            self.change_value.setText("还没有记录")
            self.change_value.set_tone("muted")
        self._rebuild_history(valuations)

    def _rebuild_history(self, valuations: list[AccountValuation]) -> None:
        clear_layout(self.history_layout)
        if not valuations:
            empty = QLabel("记录第一笔市值后，这里会出现历史曲线。")
            empty.setProperty("role", "faint")
            empty.setContentsMargins(2, 8, 2, 8)
            self.history_layout.addWidget(empty)
            self.history_layout.addStretch(1)
            return
        for valuation in valuations[:12]:
            row = _HistoryRow(valuation, self.symbol)
            row.delete_requested.connect(self._delete)
            self.history_layout.addWidget(row)
        self.history_layout.addStretch(1)

    def _delete(self, valuation_id: int) -> None:
        if not ConfirmDialog.confirm(
            self,
            "删除市值记录",
            "删除后，账户余额会按剩余记录重新计算。确定删除吗？",
            ok_text="删除",
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            self.service.delete_valuation(valuation_id)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self._refresh()

    def _save(self) -> None:
        day = self.date_input.date().toString("yyyy-MM-dd")
        try:
            value = parse_signed_amount(self.amount_input.text())
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.amount_input.setFocus()
            return
        if value < 0:
            show_error(self.error, "市值不能为负数")
            self.amount_input.setFocus()
            return
        note = self.note_input.text().strip()
        try:
            self.service.set_valuation(self.account.id, day, value, note)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.error.clear()
        self.amount_input.clear()
        self.note_input.clear()
        self._refresh()
