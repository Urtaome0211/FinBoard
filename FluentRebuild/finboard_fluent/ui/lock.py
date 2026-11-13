"""Full-window application lock overlay (requires an encrypted database)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..i18n import t
from .fluent_controls import LineEdit
from .widgets import ThemedButton


class UnlockOverlay(QWidget):
    """Blocks the whole window until the database password is entered."""

    submitted = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("LockOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#LockOverlay { background: rgba(12, 18, 30, 232); }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        card = QWidget()
        card.setObjectName("LockCard")
        card.setFixedWidth(380)
        card.setStyleSheet(
            "QWidget#LockCard { background: #ffffff; border-radius: 12px; }"
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(28, 26, 28, 26)
        body.setSpacing(12)
        title = QWidget()
        from PySide6.QtWidgets import QLabel

        heading = QLabel(t("应用已锁定"))
        heading.setStyleSheet("font-size: 22px; font-weight: 600; color: #1f2937;")
        body.addWidget(heading)
        hint = QLabel(t("请输入数据库密码以继续"))
        hint.setStyleSheet("color: #6b7280;")
        body.addWidget(hint)
        self.input = LineEdit()
        self.input.setEchoMode(LineEdit.EchoMode.Password)
        self.input.setPlaceholderText(t("数据库密码"))
        self.input.returnPressed.connect(self._submit)
        body.addWidget(self.input)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #d83b3b;")
        body.addWidget(self.error)
        button = ThemedButton(t("解锁"), "primary")
        button.clicked.connect(self._submit)
        body.addWidget(button)
        row = QWidget()
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.input.setFocus()

    def _submit(self) -> None:
        value = self.input.text()
        if value:
            self.submitted.emit(value)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.input.selectAll()
        self.input.setFocus()

    def clear(self) -> None:
        self.input.clear()
        self.error.clear()
