"""Reusable flat widgets shared by every page."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.dates import month_choices, month_label, today, month_of
from .icons import app_icon, icon, set_button_icon
from .theme import colors, theme_store, tone_for_ratio


def _weight(value: int) -> QFont.Weight:
    if value >= 700:
        return QFont.Weight.Bold
    if value >= 600:
        return QFont.Weight.DemiBold
    if value >= 500:
        return QFont.Weight.Medium
    return QFont.Weight.Normal


class ValueLabel(QLabel):
    """Label whose colour follows a semantic tone and the active theme."""

    def __init__(
        self,
        text: str = "",
        *,
        tone: str = "text",
        size: int = 24,
        weight: int = 700,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._tone = tone
        font = self.font()
        font.setPixelSize(size)
        font.setWeight(_weight(weight))
        self.setFont(font)
        theme_store.changed.connect(self._refresh)
        self._refresh()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._refresh()

    def tone(self) -> str:
        return self._tone

    def _refresh(self) -> None:
        palette = colors()
        mapping = {
            "text": palette.text,
            "muted": palette.muted,
            "faint": palette.faint,
            "income": palette.income,
            "expense": palette.expense,
            "primary": palette.primary,
            "warning": palette.warning,
            "danger": palette.danger,
        }
        self.setStyleSheet(
            f"color: {mapping.get(self._tone, palette.text)}; background: transparent;"
        )


class Dot(QWidget):
    def __init__(self, color: str, size: int = 9, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect())


class Badge(QLabel):
    """Small tinted pill used for status and transaction kinds."""

    _TONES = {
        "neutral": ("muted", "surface_alt"),
        "primary": ("primary", "primary_soft"),
        "success": ("income", "income_soft"),
        "danger": ("expense", "expense_soft"),
        "warning": ("warning", "warning_soft"),
        "accent": ("accent", "accent_soft"),
        "info": ("info", "info_soft"),
    }

    def __init__(
        self, text: str = "", tone: str = "neutral", parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self._tone = tone
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme_store.changed.connect(self._refresh)
        self._refresh()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._refresh()

    def _refresh(self) -> None:
        palette = colors()
        fg_key, bg_key = self._TONES.get(self._tone, self._TONES["neutral"])
        fg = getattr(palette, fg_key)
        bg = getattr(palette, bg_key)
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border: none;"
            " border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: bold; }"
        )


class Card(QFrame):
    """White surface with a thin border and comfortable padding."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        padding: int = 20,
        spacing: int = 12,
        object_name: str = "Card",
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def add_header(
        self,
        title: str,
        hint: str = "",
        action: QWidget | None = None,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        column = QVBoxLayout()
        column.setSpacing(3)
        title_label = QLabel(title)
        title_label.setProperty("role", "cardTitle")
        column.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "muted")
            column.addWidget(hint_label)
        row.addLayout(column)
        row.addStretch(1)
        if action is not None:
            row.addWidget(action, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)
        return row


class PageHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        column = QVBoxLayout()
        column.setSpacing(4)
        self.title_label = QLabel(title, self)
        self.title_label.setProperty("role", "pageTitle")
        column.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setProperty("role", "pageSubtitle")
        column.addWidget(self.subtitle_label)
        self.subtitle_label.setVisible(bool(subtitle))
        row.addLayout(column)
        row.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(9)
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))


class Page(QWidget):
    """Page scaffold with consistent margins; optionally scrollable."""

    def __init__(self, *, scroll: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll_area: QScrollArea | None = None
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content.setObjectName("PageContent")
            self.body = QVBoxLayout(content)
            self.body.setContentsMargins(28, 24, 28, 28)
            self.body.setSpacing(18)
            area.setWidget(content)
            outer.addWidget(area)
            self.scroll_area = area
        else:
            self.body = QVBoxLayout(self)
            self.body.setContentsMargins(28, 24, 28, 24)
            self.body.setSpacing(16)


class SearchInput(QLineEdit):
    def __init__(
        self, placeholder: str = "搜索…", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SearchInput")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(220)
        self._search_action = self.addAction(
            icon("search", colors().faint, 17), QLineEdit.ActionPosition.LeadingPosition
        )
        theme_store.changed.connect(self._refresh)

    def _refresh(self) -> None:
        self._search_action.setIcon(icon("search", colors().faint, 17))


class ComboBox(QComboBox):
    """QComboBox with a consistently drawn chevron in both themes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme_store.changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        palette = colors()
        color = palette.faint if not self.isEnabled() else palette.muted
        painter = QPainter(self)
        chevron = icon("chevron-down", color, 14)
        chevron.paint(
            painter,
            QRect(self.width() - 25, (self.height() - 14) // 2, 14, 14),
        )
        painter.end()


class MonthCombo(ComboBox):
    def __init__(
        self,
        *,
        include_all: bool = False,
        count: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(148)
        if include_all:
            self.addItem("全部月份", None)
        for month in month_choices(count):
            self.addItem(month_label(month), month)
        self.set_month(month_of(today()))

    def current_month(self) -> str | None:
        data = self.currentData()
        return str(data) if data else None

    def set_month(self, month: str | None) -> None:
        index = self.findData(month)
        if index >= 0:
            self.setCurrentIndex(index)


class NavButton(QPushButton):
    def __init__(
        self, icon_name: str, text: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(19, 19))
        self.toggled.connect(self._refresh)
        theme_store.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        palette = colors()
        color = palette.primary if self.isChecked() else palette.muted
        set_button_icon(self, self._icon_name, color, 19)


class ThemedButton(QPushButton):
    def __init__(
        self,
        text: str,
        kind: str = "primary",
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._kind = kind
        self._icon_name = icon_name
        object_names = {
            "primary": "PrimaryButton",
            "secondary": "SecondaryButton",
            "ghost": "GhostButton",
            "danger": "DangerButton",
            "soft": "SoftButton",
            "link": "LinkButton",
        }
        self.setObjectName(object_names.get(kind, "SecondaryButton"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(17, 17))
        theme_store.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def _icon_color(self) -> str:
        palette = colors()
        if self._kind in ("primary", "danger"):
            return "#FFFFFF"
        if self._kind == "soft":
            return palette.primary
        if self._kind == "link":
            return palette.primary
        return palette.muted

    def _refresh_icon(self) -> None:
        if self._icon_name:
            set_button_icon(self, self._icon_name, self._icon_color(), 17)


class IconButton(QPushButton):
    def __init__(
        self,
        icon_name: str,
        tooltip: str = "",
        *,
        color: str | None = None,
        size: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self._size = size
        self.setObjectName("IconButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        theme_store.changed.connect(self._refresh)
        self._refresh()

    def set_icon_name(self, name: str) -> None:
        self._icon_name = name
        self._refresh()

    def _refresh(self) -> None:
        set_button_icon(self, self._icon_name, self._color or colors().muted, self._size)


class SegmentedControl(QWidget):
    changed = Signal(object)

    def __init__(
        self,
        options: list[tuple[str, object]],
        current: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buttons: list[tuple[object, QPushButton]] = []
        self._value: object | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("Segment")
        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(3, 3, 3, 3)
        frame_layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for label, value in options:
            button = QPushButton(label)
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, value=value: self._choose(value)
            )
            self._group.addButton(button)
            frame_layout.addWidget(button)
            self._buttons.append((value, button))
        layout.addWidget(frame)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_value(current if current is not None else options[0][1], emit=False)

    def _choose(self, value: object) -> None:
        if value == self._value:
            return
        self._value = value
        self.changed.emit(value)

    def value(self) -> object | None:
        return self._value

    def set_value(self, value: object, *, emit: bool = False) -> None:
        for option_value, button in self._buttons:
            if option_value == value:
                button.setChecked(True)
                self._value = value
                if emit:
                    self.changed.emit(value)
                return


class EmptyState(QWidget):
    def __init__(
        self,
        icon_name: str,
        title: str,
        hint: str = "",
        action_text: str = "",
        on_action: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 40, 24, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge = QLabel(self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedSize(56, 56)
        layout.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self._icon_name = icon_name
        self._title = QLabel(title, self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = self._title.font()
        title_font.setPixelSize(16)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title.setFont(title_font)
        layout.addWidget(self._title)
        self._hint = QLabel(hint, self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setProperty("role", "muted")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        self._hint.setVisible(bool(hint))
        if action_text and on_action is not None:
            button = ThemedButton(action_text, "secondary", "plus")
            button.clicked.connect(on_action)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        theme_store.changed.connect(self._refresh_theme)
        self._refresh_theme()

    def _refresh_theme(self) -> None:
        palette = colors()
        self._badge.setPixmap(icon(self._icon_name, palette.primary, 26).pixmap(26, 26))
        self._badge.setStyleSheet(
            f"background: {palette.primary_soft}; border-radius: 16px;"
        )


class ConfirmDialog(QDialog):
    """Flat replacement for QMessageBox."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        ok_text: str = "确定",
        cancel_text: str | None = "取消",
        danger: bool = False,
        icon_name: str = "info",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(14)
        badge = QLabel()
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        palette = colors()
        badge_color = palette.danger_soft if danger else palette.primary_soft
        glyph = palette.danger if danger else palette.primary
        badge.setPixmap(icon(icon_name, glyph, 21).pixmap(21, 21))
        badge.setStyleSheet(f"background: {badge_color}; border-radius: 12px;")
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        heading = QLabel(title)
        heading.setWordWrap(True)
        font = heading.font()
        font.setPixelSize(17)
        font.setWeight(QFont.Weight.DemiBold)
        heading.setFont(font)
        top.addWidget(heading, 1)
        layout.addLayout(top)

        text = QLabel(message)
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setProperty("role", "muted")
        text.setContentsMargins(56, 0, 0, 0)
        layout.addWidget(text)

        buttons = QHBoxLayout()
        buttons.setSpacing(9)
        buttons.addStretch(1)
        if cancel_text:
            cancel = ThemedButton(cancel_text, "secondary")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)
        confirm = ThemedButton(ok_text, "danger" if danger else "primary")
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    @classmethod
    def confirm(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        ok_text: str = "确定",
        cancel_text: str = "取消",
        danger: bool = False,
        icon_name: str | None = None,
    ) -> bool:
        dialog = cls(
            parent,
            title,
            message,
            ok_text=ok_text,
            cancel_text=cancel_text,
            danger=danger,
            icon_name=icon_name or ("alert" if danger else "info"),
        )
        return dialog.exec() == QDialog.DialogCode.Accepted

    @classmethod
    def alert(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        ok_text: str = "知道了",
        icon_name: str = "info",
    ) -> None:
        dialog = cls(
            parent,
            title,
            message,
            ok_text=ok_text,
            cancel_text=None,
            icon_name=icon_name,
        )
        dialog.exec()


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def progress_bar(value: float, tone: str | None = None) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(max(0, min(100, int(round(value)))))
    bar.setTextVisible(False)
    bar.setProperty("tone", tone)
    return bar


def set_progress(bar: QProgressBar, ratio: float, *, force_tone: str | None = None) -> None:
    bar.setValue(max(0, min(100, int(round(ratio)))))
    tone = force_tone or tone_for_ratio(ratio)
    if bar.property("tone") != tone:
        bar.setProperty("tone", tone)
        style = bar.style()
        style.unpolish(bar)
        style.polish(bar)
        bar.update()


def set_error(widget: QWidget, invalid: bool) -> None:
    if widget.property("invalid") == invalid:
        return
    widget.setProperty("invalid", invalid)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def icon_label(name: str, color: str, size: int = 18, background: str | None = None,
               box: int = 38, radius: int = 11) -> QLabel:
    label = QLabel()
    label.setFixedSize(box, box)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setPixmap(icon(name, color, size).pixmap(size, size))
    if background:
        label.setStyleSheet(f"background: {background}; border-radius: {radius}px;")
    return label


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)
            child.deleteLater()
