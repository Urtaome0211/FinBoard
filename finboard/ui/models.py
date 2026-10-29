"""Table model and delegates for the transaction ledger."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from ..core.models import KIND_LABELS, Transaction
from ..core.service import FinanceService
from .theme import colors

_HEADERS = ("日期", "类型", "交易", "分类", "账户", "金额", "手续费")


class TransactionTableModel(QAbstractTableModel):
    def __init__(self, service: FinanceService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self._rows: list[Transaction] = []
        self._dot_cache: dict[str, QPixmap] = {}

    # ------------------------------------------------------------- Qt plumbing
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        txn = self._rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.UserRole:
            return txn
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return txn.date
            if column == 1:
                return KIND_LABELS.get(txn.kind, txn.kind)
            if column == 2:
                return txn.title
            if column == 3:
                return txn.category_name or "—"
            if column == 4:
                return txn.account_display
            if column == 5:
                if txn.kind == "expense":
                    money = self.service.format_money(-txn.amount, txn.currency)
                elif txn.kind == "income":
                    money = self.service.format_money(
                        txn.amount, txn.currency, plus=True
                    )
                else:
                    money = self.service.format_money(txn.amount, txn.currency)
                    if txn.currency != txn.to_account_currency:
                        money += " → " + self.service.format_money(
                            txn.to_amount, txn.to_account_currency
                        )
                    elif txn.currency != self.service.currency:
                        money += f" {txn.currency}"
                if txn.kind != "transfer" and txn.currency != self.service.currency:
                    money += f" {txn.currency}"
                return money
            if column == 6:
                if txn.kind == "transfer" and txn.fee:
                    return self.service.format_money(txn.fee, txn.account_currency)
                return ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (5, 6):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column == 1:
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            palette = colors()
            if column == 6:
                return QColor(palette.expense) if txn.fee else QColor(palette.faint)
            if column == 5:
                if txn.kind == "income":
                    return QColor(palette.income)
                if txn.kind == "expense":
                    return QColor(palette.expense)
                return QColor(palette.muted)
            if column in (0, 1):
                return QColor(palette.muted)
            return QColor(palette.text)
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setPixelSize(13)
            if column in (5, 6):
                font.setWeight(QFont.Weight.DemiBold)
            elif column == 2:
                font.setWeight(QFont.Weight.Medium)
            return font
        if role == Qt.ItemDataRole.DecorationRole and column == 3 and txn.category_color:
            return self._dot(txn.category_color)
        if role == Qt.ItemDataRole.ToolTipRole:
            detail = f"{txn.date}  {txn.title}"
            if txn.note:
                detail += f"\n{txn.note}"
            detail += f"\n{txn.account_display}"
            if txn.currency != txn.account_currency:
                detail += (
                    f"\n账户入账 {self.service.format_money(txn.account_amount, txn.account_currency)}"
                )
            if txn.kind == "transfer" and txn.to_amount:
                detail += (
                    f"\n到账 {self.service.format_money(txn.to_amount, txn.to_account_currency)}"
                )
            if txn.fee:
                detail += (
                    f"\n手续费 {self.service.format_money(txn.fee, txn.account_currency)}"
                    "（从转出账户扣除）"
                )
            return detail
        return None

    def _dot(self, color: str) -> QPixmap:
        cached = self._dot_cache.get(color)
        if cached is not None:
            return cached
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(3, 3, 8, 8)
        painter.end()
        self._dot_cache[color] = pixmap
        return pixmap

    # ------------------------------------------------------------------ helpers
    def set_transactions(self, rows: list[Transaction]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def transaction_at(self, row: int) -> Transaction | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


class KindBadgeDelegate(QStyledItemDelegate):
    """Paint the transaction kind as a small tinted pill."""

    _TONES = {
        "expense": ("expense", "expense_soft"),
        "income": ("income", "income_soft"),
        "transfer": ("primary", "primary_soft"),
    }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        palette = colors()
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(palette.selection))
        txn = index.data(Qt.ItemDataRole.UserRole)
        kind = getattr(txn, "kind", "expense")
        fg_key, bg_key = self._TONES.get(kind, ("muted", "surface_alt"))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect
        pill = QRectF(
            rect.center().x() - 25,
            rect.center().y() - 11,
            50,
            22,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(getattr(palette, bg_key)))
        painter.drawRoundedRect(pill, 6, 6)
        font = painter.font()
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(getattr(palette, fg_key)))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()
