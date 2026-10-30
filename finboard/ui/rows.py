"""Compact list rows used on the dashboard and the accounts page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.models import Account, Transaction
from ..core.service import FinanceService
from ..i18n import account_type_display, category_display, t
from .theme import colors, theme_store
from .widgets import Badge, IconButton, ValueLabel, icon_label


class ElidedLabel(QLabel):
    """A label that elides instead of clipping when the row gets narrow."""

    def __init__(
        self,
        text: str = "",
        *,
        role: str = "text",
        size: int = 13,
        weight: int = 500,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._role = role
        self._text = text
        font = self.font()
        font.setPixelSize(size)
        font.setWeight(
            QFont.Weight.Bold
            if weight >= 700
            else QFont.Weight.DemiBold
            if weight >= 600
            else QFont.Weight.Medium
            if weight >= 500
            else QFont.Weight.Normal
        )
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        theme_store.changed.connect(self.update)

    def setText(self, text: str) -> None:  # noqa: N802
        self._text = text
        self.setToolTip(text)
        self.update()

    def text(self) -> str:
        return self._text

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(QColor(getattr(colors(), self._role, colors().text)))
        text = self.fontMetrics().elidedText(
            self._text, Qt.TextElideMode.ElideRight, self.width()
        )
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class TransactionRow(QFrame):
    clicked = Signal(object)

    def __init__(
        self,
        transaction: Transaction,
        service: FinanceService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.transaction = transaction
        self.setObjectName("TxnRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(58)
        palette = colors()
        if transaction.kind == "income":
            color, background = palette.income, palette.income_soft
            amount = service.format_money(
                transaction.amount, transaction.currency, plus=True
            )
            tone = "income"
        elif transaction.kind == "expense":
            color, background = palette.expense, palette.expense_soft
            amount = service.format_money(-transaction.amount, transaction.currency)
            tone = "expense"
        else:
            color, background = palette.primary, palette.primary_soft
            amount = service.format_money(transaction.amount, transaction.currency)
            tone = "muted"
        if transaction.currency != service.currency:
            amount += f" {transaction.currency}"

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)
        row.addWidget(icon_label(transaction.kind, color, 17, background, box=34, radius=10))

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        text_column.setContentsMargins(0, 0, 0, 0)
        title = ElidedLabel(transaction.title, size=13, weight=600)
        title.setProperty("i18nSkip", True)
        subtitle_text = (
            f"{category_display(transaction.category_name)} · {transaction.account_display}"
            if transaction.kind != "transfer"
            else f"{t('转账')} · {transaction.account_display}"
        )
        if transaction.fee:
            subtitle_text += (
                f" · {t('手续费')} {service.format_money(transaction.fee, transaction.account_currency)}"
            )
            if transaction.fee_included:
                subtitle_text += f"（{t('包含在提现金额中')}）"
        elif transaction.kind == "transfer" and transaction.fee_waived:
            subtitle_text += f" · {t('手续费已豁免')}"
        if transaction.currency != service.currency:
            subtitle_text += f" · {transaction.currency}"
        subtitle = ElidedLabel(
            subtitle_text,
            role="muted",
            size=11,
            weight=400,
        )
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        row.addLayout(text_column, 1)

        date = QLabel(transaction.date[5:])
        date.setProperty("role", "muted")
        date.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        date.setFixedWidth(44)
        row.addWidget(date)

        amount_label = ValueLabel(amount, tone=tone, size=14, weight=600)
        amount_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount_label.setMinimumWidth(96)
        row.addWidget(amount_label)
        if transaction.fee:
            included = (
                f"（{t('包含在提现金额中')}）" if transaction.fee_included else ""
            )
            self.setToolTip(
                f"手续费 {service.format_money(transaction.fee, transaction.account_currency)}{included}"
                f"\n从「{transaction.account_name}」转出时自动扣除"
            )
        elif transaction.kind == "transfer" and transaction.fee_waived:
            self.setToolTip(t("手续费已豁免"))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.transaction)
        super().mouseReleaseEvent(event)


class AccountRow(QFrame):
    edit_requested = Signal(object)
    archive_requested = Signal(object)
    delete_requested = Signal(object)
    valuation_requested = Signal(object)
    holdings_requested = Signal(object)
    reconcile_requested = Signal(object)

    def __init__(
        self, account: Account, service: FinanceService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.account = account
        self.setObjectName("AccountRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(66)
        palette = colors()
        is_liability = account.is_liability
        color = palette.expense if is_liability else palette.primary
        background = palette.expense_soft if is_liability else palette.primary_soft

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)
        row.addWidget(icon_label(account.icon_name, color, 18, background, box=38, radius=11))

        column = QVBoxLayout()
        column.setSpacing(2)
        column.setContentsMargins(0, 0, 0, 0)
        name_row = QHBoxLayout()
        name_row.setSpacing(7)
        name_label = ElidedLabel(account.name, size=13, weight=600)
        name_label.setProperty("i18nSkip", True)
        name_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        name_label.setMinimumWidth(60)
        name_row.addWidget(name_label)
        name_row.addWidget(Badge(account_type_display(account.type_label), "danger" if is_liability else "primary"))
        if account.archived:
            name_row.addWidget(Badge(t("已归档"), "neutral"))
        name_row.addStretch(1)
        column.addLayout(name_row)
        note = account.note or t("负债账户" if is_liability else "资产账户")
        if account.type == "investment":
            note = account.note or t("投资账户")
            note = (
                f"{note} · {t('现金')} "
                f"{service.format_money(account.cash_balance, account.currency)}"
                f" · {t('持仓')} "
                f"{service.format_money(account.holdings_value, account.currency)}"
            )
            if account.last_valuation_date:
                note = f"{note} · {t('市值')} {account.last_valuation_date}"
        if account.currency != "CNY":
            note = f"{account.currency} · {note}"
        if account.adjustment:
            note += f" · {t('对账调整')} {service.format_money(account.adjustment, account.currency)}"
        note_label = ElidedLabel(note, role="muted", size=11, weight=400)
        note_label.setProperty("i18nSkip", True)
        column.addWidget(note_label)
        row.addLayout(column, 1)

        display_balance = -abs(account.balance) if is_liability and account.balance > 0 else account.balance
        balance = ValueLabel(
            service.format_money(display_balance, account.currency),
            tone="expense" if display_balance < 0 else ("muted" if display_balance == 0 else "text"),
            size=15,
            weight=600,
        )
        if is_liability and account.balance > 0:
            balance.setToolTip(t("负债账户按欠款显示；打开账户并保存可修正符号"))
        balance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        balance.setMinimumWidth(116)
        row.addWidget(balance)

        actions = QHBoxLayout()
        actions.setSpacing(0)
        holdings = IconButton("investment", t("持仓与成本"), size=16)
        holdings.setFixedSize(30, 30)
        holdings.setVisible(account.type == "investment" and not account.archived)
        valuation = IconButton("chart", t("记录每日市值"), size=16)
        valuation.setFixedSize(30, 30)
        valuation.setVisible(account.type == "investment" and not account.archived)
        reconcile = IconButton("check", t("对账校准余额"), size=16)
        reconcile.setFixedSize(30, 30)
        reconcile.setVisible(account.type != "investment" and not account.archived)
        edit = IconButton("edit", t("编辑账户"), size=16)
        archive = IconButton(
            "refresh" if account.archived else "archive",
            t("恢复账户") if account.archived else t("归档账户"),
            size=16,
        )
        delete = IconButton("trash", t("删除账户"), size=16)
        for button in (holdings, valuation, reconcile, edit, archive, delete):
            button.setFixedSize(30, 30)
            actions.addWidget(button)
        holdings.clicked.connect(lambda: self.holdings_requested.emit(account))
        valuation.clicked.connect(lambda: self.valuation_requested.emit(account))
        reconcile.clicked.connect(lambda: self.reconcile_requested.emit(account))
        edit.clicked.connect(lambda: self.edit_requested.emit(account))
        archive.clicked.connect(lambda: self.archive_requested.emit(account))
        delete.clicked.connect(lambda: self.delete_requested.emit(account))
        row.addLayout(actions)
