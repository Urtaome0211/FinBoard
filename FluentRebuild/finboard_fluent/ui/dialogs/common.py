"""Shared pieces for the small modal forms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from ..theme import colors
from ..widgets import ThemedButton, icon_label


def color_icon(color: str, size: int = 12) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


def dialog_header(
    title: str, subtitle: str = "", icon_name: str = "plus"
) -> tuple[QHBoxLayout, QLabel]:
    palette = colors()
    row = QHBoxLayout()
    row.setSpacing(13)
    row.addWidget(
        icon_label(icon_name, palette.primary, 20, palette.primary_soft, box=42, radius=12),
        0,
        Qt.AlignmentFlag.AlignTop,
    )
    column = QVBoxLayout()
    column.setSpacing(2)
    heading = QLabel(title)
    heading.setProperty("role", "dialogTitle")
    column.addWidget(heading)
    if subtitle:
        hint = QLabel(subtitle)
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        column.addWidget(hint)
    row.addLayout(column, 1)
    return row, heading


def form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setMinimumWidth(62)
    return label


def dialog_footer(
    dialog: QDialog,
    error_label: QLabel,
    *,
    save_text: str = "保存",
    cancel_text: str = "取消",
) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    row.addWidget(error_label, 1)
    cancel = ThemedButton(cancel_text, "secondary")
    cancel.clicked.connect(dialog.reject)
    save = ThemedButton(save_text, "primary")
    save.setDefault(True)
    row.addWidget(cancel)
    row.addWidget(save)
    return row


def error_label() -> QLabel:
    label = QLabel()
    label.setProperty("role", "error")
    label.setWordWrap(True)
    label.hide()
    return label


def show_error(label: QLabel, message: str) -> None:
    label.setText(message)
    label.setVisible(bool(message))


def root_layout(dialog: QDialog) -> QVBoxLayout:
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(26, 24, 26, 22)
    layout.setSpacing(17)
    return layout


__all__ = [
    "color_icon",
    "dialog_header",
    "dialog_footer",
    "error_label",
    "form_label",
    "root_layout",
    "show_error",
]
