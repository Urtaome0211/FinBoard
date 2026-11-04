"""Small page-level building blocks shared by the dashboard and reports."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..icons import icon
from ..theme import colors, theme_store
from ..widgets import Card, Dot, ValueLabel, icon_label


_TONE_KEYS = {
    "primary": ("primary", "primary_soft"),
    "income": ("income", "income_soft"),
    "expense": ("expense", "expense_soft"),
    "warning": ("warning", "warning_soft"),
    "accent": ("accent", "accent_soft"),
    "muted": ("muted", "surface_alt"),
}


class StatCard(Card):
    """Compact KPI tile with icon, value and a contextual hint."""

    def __init__(
        self,
        title: str,
        icon_name: str,
        *,
        tone: str = "primary",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, padding=18, spacing=8)
        self._icon_name = icon_name
        self._tone = tone
        self._value_tone = tone if tone in ("income", "expense", "warning") else "text"
        self.setMinimumHeight(128)

        top = QHBoxLayout()
        top.setSpacing(9)
        self._badge = QLabel()
        self._badge.setFixedSize(32, 32)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self._badge)
        title_label = QLabel(title)
        title_label.setProperty("role", "muted")
        top.addWidget(title_label)
        top.addStretch(1)
        self.body.addLayout(top)

        self.value = ValueLabel("—", tone=self._value_tone, size=26, weight=700)
        self.body.addWidget(self.value)
        self.hint = QLabel("")
        self.hint.setProperty("role", "faint")
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.body.addWidget(self.hint)
        self.body.addStretch(1)

        theme_store.changed.connect(self._refresh_theme)
        self._refresh_theme()

    def set_value(self, text: str, *, hint: str = "", tone: str | None = None) -> None:
        self.value.setText(text)
        if tone:
            self._value_tone = tone
            self.value.set_tone(tone)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))

    def _refresh_theme(self) -> None:
        palette = colors()
        fg_key, bg_key = _TONE_KEYS.get(self._tone, _TONE_KEYS["primary"])
        fg = getattr(palette, fg_key)
        bg = getattr(palette, bg_key)
        self._badge.setPixmap(icon(self._icon_name, fg, 17).pixmap(17, 17))
        self._badge.setStyleSheet(f"background: {bg}; border-radius: 9px;")


class LegendRow(QWidget):
    """Coloured dot, label and a right-aligned amount / percentage."""

    def __init__(
        self,
        color: str,
        label: str,
        *,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dot = Dot(color, 9)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._dot)
        self.label = QLabel(label)
        self.label.setProperty("role", "muted")
        row.addWidget(self.label)
        row.addStretch(1)
        self.value = ValueLabel("", tone="text", size=12 if compact else 13, weight=600)
        row.addWidget(self.value)
        self.percent = QLabel("")
        self.percent.setProperty("role", "faint")
        self.percent.setMinimumWidth(42)
        self.percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        row.addWidget(self.percent)

    def set_data(self, value: str, percent: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.percent.setText(percent)
        if color:
            self._dot.set_color(color)


def card_title(title: str, hint: str = "") -> QVBoxLayout:
    """Small vertical title block that can be inserted into a custom row."""
    column = QVBoxLayout()
    column.setSpacing(3)
    title_label = QLabel(title)
    title_label.setProperty("role", "cardTitle")
    column.addWidget(title_label)
    if hint:
        hint_label = QLabel(hint)
        hint_label.setProperty("role", "muted")
        hint_label.setWordWrap(True)
        column.addWidget(hint_label)
    return column


def small_icon_badge(
    name: str,
    *,
    color: str | None = None,
    background: str | None = None,
    box: int = 34,
    radius: int = 10,
) -> QLabel:
    palette = colors()
    return icon_label(
        name,
        color or palette.primary,
        background=background or palette.primary_soft,
        box=box,
        radius=radius,
    )
