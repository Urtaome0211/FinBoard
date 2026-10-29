"""Hand-painted charts: donut, trend line and ranked category bars."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.dates import short_month_label
from ..core.models import AccountValuation, CategorySpend, MonthStats
from ..core.money import format_cents, format_compact, format_percentage, percentage
from .theme import colors, theme_store


class DonutChart(QWidget):
    """Ring chart with a two-line centre label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._segments: list[tuple[str, int, str]] = []
        self._center_title = ""
        self._center_value = ""
        self._empty_text = "暂无数据"
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme_store.changed.connect(self.update)

    def set_data(
        self,
        segments: list[tuple[str, int, str]],
        *,
        center_title: str = "",
        center_value: str = "",
        empty_text: str = "暂无数据",
    ) -> None:
        self._segments = [(label, max(0, int(value)), color) for label, value, color in segments]
        self._center_title = center_title
        self._center_value = center_value
        self._empty_text = empty_text
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height()) - 12
        if side <= 20:
            return
        ring = QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )
        thickness = max(14.0, side * 0.105)
        inner = ring.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)

        track_pen = QPen(QColor(palette.surface_alt), thickness)
        track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(track_pen)
        painter.drawArc(inner, 0, 360 * 16)

        total = sum(value for _, value, _ in self._segments)
        if total > 0:
            gap = 2.0 if len([v for v in self._segments if v[1] > 0]) > 1 else 0.0
            start = 90.0
            for _, value, color in self._segments:
                if value <= 0:
                    continue
                span = value / total * 360.0
                pen = QPen(QColor(color), thickness)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawArc(
                    inner,
                    int((start - gap / 2) * 16),
                    int(-(span - gap) * 16),
                )
                start -= span

        center = QRectF(ring.left(), ring.top(), side, side)
        if self._center_title:
            title_font = QFont(self.font())
            title_font.setPixelSize(max(11, int(side * 0.065)))
            painter.setFont(title_font)
            painter.setPen(QColor(palette.muted))
            painter.drawText(
                QRectF(center.left(), center.center().y() - side * 0.15, side, side * 0.18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                self._center_title,
            )
        value = self._center_value or (format_percentage(total, total) if total else self._empty_text)
        value_font = QFont(self.font())
        value_font.setPixelSize(max(20, int(side * 0.12)))
        value_font.setWeight(QFont.Weight.Bold)
        painter.setFont(value_font)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            QRectF(center.left(), center.center().y() - side * 0.02, side, side * 0.24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            value,
        )
        painter.end()


class TrendChart(QWidget):
    """Income / expense lines with hover inspection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stats: list[MonthStats] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme_store.changed.connect(self.update)

    def set_data(self, stats: list[MonthStats]) -> None:
        self._stats = list(stats)
        self._hover = -1
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(56, 40, max(10.0, self.width() - 74), max(10.0, self.height() - 76))

    def _point(self, index: int, value: int, maximum: int) -> QPointF:
        rect = self._plot_rect()
        count = max(1, len(self._stats))
        x = rect.left() + (rect.width() * index / max(1, count - 1))
        y = rect.bottom() - rect.height() * (value / maximum if maximum else 0)
        return QPointF(x, y)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._stats:
            return
        rect = self._plot_rect()
        if rect.left() <= event.position().x() <= rect.right():
            ratio = (event.position().x() - rect.left()) / max(1.0, rect.width())
            index = int(round(ratio * (len(self._stats) - 1)))
            index = max(0, min(len(self._stats) - 1, index))
            if index != self._hover:
                self._hover = index
                self.update()
        elif self._hover != -1:
            self._hover = -1
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._stats:
            painter.setPen(QColor(palette.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无趋势数据")
            return
        rect = self._plot_rect()
        incomes = [item.income for item in self._stats]
        expenses = [item.expense for item in self._stats]
        peak = max(max(incomes, default=0), max(expenses, default=0))
        maximum = _nice_ceiling(peak)
        if maximum <= 0:
            maximum = 100

        grid_pen = QPen(QColor(palette.chart_grid), 1)
        label_font = QFont(self.font())
        label_font.setPixelSize(11)
        painter.setFont(label_font)
        for step in range(5):
            value = int(maximum * step / 4)
            y = rect.bottom() - rect.height() * (value / maximum)
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor(palette.faint))
            painter.drawText(
                QRectF(0, y - 9, rect.left() - 10, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_compact(value),
            )

        count = len(self._stats)
        every = 2 if count > 8 else 1
        for index, item in enumerate(self._stats):
            if index % every != 0 and index != count - 1:
                continue
            x = rect.left() + rect.width() * index / max(1, count - 1)
            painter.setPen(QColor(palette.faint))
            painter.drawText(
                QRectF(x - 24, rect.bottom() + 10, 48, 18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                short_month_label(item.month),
            )

        for series, color in ((incomes, palette.income), (expenses, palette.expense)):
            path = QPainterPath()
            area = QPainterPath()
            for index, value in enumerate(series):
                point = self._point(index, value, maximum)
                if index == 0:
                    path.moveTo(point)
                    area.moveTo(point)
                else:
                    path.lineTo(point)
                    area.lineTo(point)
            area.lineTo(QPointF(rect.right(), rect.bottom()))
            area.lineTo(QPointF(rect.left(), rect.bottom()))
            area.closeSubpath()
            fill = QColor(color)
            fill.setAlpha(16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawPath(area)
            pen = QPen(QColor(color), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if self._hover >= 0:
            index = self._hover
            x = self._point(index, 0, maximum).x()
            guide = QPen(QColor(palette.border_strong), 1)
            guide.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))

        for series, color in ((incomes, palette.income), (expenses, palette.expense)):
            for index, value in enumerate(series):
                point = self._point(index, value, maximum)
                painter.setPen(QPen(QColor(color), 2))
                painter.setBrush(QColor(palette.surface))
                painter.drawEllipse(point, 3.4, 3.4)

        legend_font = QFont(self.font())
        legend_font.setPixelSize(12)
        painter.setFont(legend_font)
        legend_x = 56.0
        for label, color in (("收入", palette.income), ("支出", palette.expense)):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(legend_x, 18), 4, 4)
            painter.setPen(QColor(palette.muted))
            painter.drawText(
                QRectF(legend_x + 9, 8, 44, 20),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            legend_x += 62

        if self._hover >= 0:
            self._draw_tooltip(painter, self._hover, rect)

    def _draw_tooltip(self, painter: QPainter, index: int, rect: QRectF) -> None:
        palette = colors()
        item = self._stats[index]
        width, height = 168.0, 74.0
        point = self._point(index, item.income, _nice_ceiling(
            max(
                max((s.income for s in self._stats), default=0),
                max((s.expense for s in self._stats), default=0),
            )
        ) or 100)
        left = point.x() + 12
        if left + width > self.width() - 8:
            left = point.x() - width - 12
        left = max(8.0, left)
        top = max(8.0, rect.top() - 4)
        box = QRectF(left, top, width, height)
        shadow = QColor(palette.text)
        shadow.setAlpha(12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(box.adjusted(0, 2, 0, 2), 10, 10)
        painter.setBrush(QColor(palette.surface))
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.drawRoundedRect(box, 10, 10)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            box.adjusted(12, 8, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            item.month,
        )
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(palette.income))
        painter.drawText(
            box.adjusted(12, 30, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"收入  {format_compact(item.income)}",
        )
        painter.setPen(QColor(palette.expense))
        painter.drawText(
            box.adjusted(12, 48, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            f"支出  {format_compact(item.expense)}",
        )


class ValuationChart(QWidget):
    """Single-series account value history for investment accounts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[AccountValuation] = []
        self._symbol = "¥"
        self._hover = -1
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme_store.changed.connect(self.update)

    def set_data(self, items: list[AccountValuation], symbol: str = "¥") -> None:
        self._items = sorted(items, key=lambda item: item.date)
        self._symbol = symbol
        self._hover = -1
        self.update()

    def _geometry(self) -> tuple[QRectF, int]:
        return (
            QRectF(58, 18, max(20.0, self.width() - 78), max(20.0, self.height() - 58)),
            max(1, max((item.value for item in self._items), default=0)),
        )

    def _x_for(self, index: int, plot: QRectF) -> float:
        if len(self._items) <= 1:
            return plot.center().x()
        return plot.left() + plot.width() * index / (len(self._items) - 1)

    def _index_at(self, x: float, plot: QRectF) -> int:
        if not self._items:
            return -1
        if len(self._items) == 1:
            return 0
        ratio = (x - plot.left()) / max(1.0, plot.width())
        return max(0, min(len(self._items) - 1, round(ratio * (len(self._items) - 1))))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        plot, _ = self._geometry()
        self._hover = self._index_at(event.position().x(), plot)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._items:
            painter.setPen(QColor(palette.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "还没有市值记录")
            return
        plot, raw_max = self._geometry()
        top = max(1, _nice_ceiling(int(raw_max * 1.08)))
        axis_font = QFont(self.font())
        axis_font.setPixelSize(11)
        painter.setFont(axis_font)
        for step in range(4, -1, -1):
            y = plot.top() + plot.height() * (4 - step) / 4
            painter.setPen(QPen(QColor(palette.chart_grid), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(palette.faint))
            painter.drawText(
                QRectF(0, y - 9, plot.left() - 10, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_compact(int(top * step / 4), self._symbol),
            )

        points: list[QPointF] = []
        for index, item in enumerate(self._items):
            x = self._x_for(index, plot)
            y = plot.bottom() - plot.height() * min(item.value, top) / top
            points.append(QPointF(x, y))
        if len(points) > 1:
            area = QPainterPath(QPointF(points[0].x(), plot.bottom()))
            area.lineTo(points[0])
            for point in points[1:]:
                area.lineTo(point)
            area.lineTo(points[-1].x(), plot.bottom())
            area.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.primary_soft))
            painter.drawPath(area)
            line = QPainterPath(points[0])
            for point in points[1:]:
                line.lineTo(point)
            pen = QPen(QColor(palette.primary), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(line)

        for index, point in enumerate(points):
            selected = index == self._hover
            painter.setPen(QPen(QColor(palette.surface), 2))
            painter.setBrush(QColor(palette.primary))
            radius = 5.2 if selected else 3.8
            painter.drawEllipse(point, radius, radius)

        label_count = len(self._items)
        stride = max(1, math.ceil(label_count / 6))
        for index, item in enumerate(self._items):
            if index % stride and index != label_count - 1:
                continue
            x = self._x_for(index, plot)
            painter.setPen(QColor(palette.faint))
            painter.drawText(
                QRectF(x - 30, plot.bottom() + 9, 60, 18),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                item.date[5:],
            )

        if self._hover >= 0:
            item = self._items[self._hover]
            point = points[self._hover]
            pen = QPen(QColor(palette.border_strong), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(point.x(), plot.top()), QPointF(point.x(), plot.bottom()))
            text = format_cents(item.value, self._symbol)
            box = QRectF(
                min(max(plot.left(), point.x() - 90), plot.right() - 190),
                max(plot.top() + 4, point.y() - 70),
                190,
                58,
            )
            painter.setPen(QPen(QColor(palette.border), 1))
            painter.setBrush(QColor(palette.surface))
            painter.drawRoundedRect(box, 10, 10)
            tip_font = QFont(self.font())
            tip_font.setPixelSize(11)
            painter.setFont(tip_font)
            painter.setPen(QColor(palette.muted))
            painter.drawText(
                box.adjusted(12, 7, -12, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                item.date,
            )
            tip_font.setPixelSize(13)
            tip_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(tip_font)
            painter.setPen(QColor(palette.text))
            painter.drawText(
                box.adjusted(12, 27, -12, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                text,
            )


class CategoryBars(QWidget):
    """Ranked horizontal bars with amount and share of total."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[CategorySpend] = []
        self._total = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme_store.changed.connect(self.update)
        self.setMinimumHeight(80)

    def set_data(self, items: list[CategorySpend], total: int | None = None) -> None:
        self._items = list(items)
        self._total = total if total is not None else sum(item.amount for item in items)
        row_height = 48
        self.setFixedHeight(max(90, len(self._items) * row_height + 8))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        palette = colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._items:
            painter.setPen(QColor(palette.faint))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无分类支出")
            return
        maximum = max(item.amount for item in self._items) or 1
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        value_font = QFont(self.font())
        value_font.setPixelSize(12)
        value_font.setWeight(QFont.Weight.DemiBold)
        percent_font = QFont(self.font())
        percent_font.setPixelSize(11)
        for index, item in enumerate(self._items):
            top = index * 48
            painter.setFont(label_font)
            painter.setPen(QColor(palette.text))
            painter.drawText(
                QRectF(0, top + 4, self.width() - 140, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.name,
            )
            painter.setFont(value_font)
            painter.setPen(QColor(palette.text))
            painter.drawText(
                QRectF(self.width() - 140, top + 4, 140, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                _short_money(item.amount),
            )
            track = QRectF(0, top + 29, max(10.0, self.width() - 52), 7)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.surface_alt))
            painter.drawRoundedRect(track, 3.5, 3.5)
            width = track.width() * item.amount / maximum
            fill = QColor(item.color)
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(track.left(), track.top(), width, 7), 3.5, 3.5)
            painter.setFont(percent_font)
            painter.setPen(QColor(palette.faint))
            painter.drawText(
                QRectF(self.width() - 45, top + 23, 45, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_percentage(item.amount, self._total),
            )


def _short_money(cents: int) -> str:
    value = cents / 100
    if value >= 10000:
        return f"¥{value / 10000:.1f}万"
    return f"¥{value:,.0f}"


def _nice_ceiling(value: int) -> int:
    if value <= 0:
        return 0
    exponent = 10 ** int(math.floor(math.log10(value)))
    fraction = value / exponent
    for nice in (1, 2, 3, 4, 5, 6, 8, 10):
        if fraction <= nice:
            return int(nice * exponent)
    return int(10 * exponent)
