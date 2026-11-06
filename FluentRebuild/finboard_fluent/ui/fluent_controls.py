"""Thin compatibility layer over qfluentwidgets controls.

The application was originally written against Qt's stock widgets.  These
classes keep the small API surface used by existing pages/dialogs while the
actual painting and interaction is provided by qfluentwidgets.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QWidget

from qfluentwidgets import (
    CheckBox,
    ComboBox as _FluentComboBox,
    DatePicker,
    LineEdit as _FluentLineEdit,
    ListWidget,
    PickerColumnFormatter,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SpinBox,
    TableWidget as _FluentTableWidget,
    TransparentToolButton,
)

__all__ = [
    "CheckBox",
    "ComboBox",
    "DateEdit",
    "LineEdit",
    "ListWidget",
    "PrimaryPushButton",
    "PushButton",
    "SearchLineEdit",
    "SpinBox",
    "TableWidget",
    "TableWidgetItem",
    "TransparentToolButton",
]


class ComboBox(_FluentComboBox):
    """Fluent combo box with the ``addItem(text, data)`` overloads we use."""

    def addItem(self, *args):  # noqa: N802
        if len(args) == 3 and isinstance(args[0], QIcon):
            icon, text, data = args
            return super().addItem(text, icon, data)
        if len(args) == 2 and isinstance(args[0], QIcon):
            icon, text = args
            return super().addItem(text, icon, None)
        if len(args) == 2:
            text, data = args
            return super().addItem(text, None, data)
        if len(args) == 1:
            return super().addItem(args[0])
        raise TypeError("addItem() takes 1 to 3 arguments")

    def addItems(self, texts):  # noqa: N802
        for text in texts:
            self.addItem(text)


class LineEdit(_FluentLineEdit):
    """Fluent line edit accepting ``(text, parent)`` like QLineEdit."""

    def __init__(self, text="", parent: QWidget | None = None) -> None:
        if isinstance(text, QWidget) and parent is None:
            parent = text
            text = ""
        super().__init__(parent)
        if text:
            self.setText(str(text))


class _NumericMonthFormatter(PickerColumnFormatter):
    def encode(self, month):
        return f"{int(month):02d}"

    def decode(self, value):
        return int(value)


class DateEdit(DatePicker):
    """DatePicker with the small QDateEdit API used in the codebase."""

    def __init__(self, date: QDate | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDateFormat(DatePicker.YYYY_MM_DD)
        self.setMonthFormatter(_NumericMonthFormatter())
        if date is not None and date.isValid():
            self.setDate(date)

    def setCalendarPopup(self, enabled: bool) -> None:  # noqa: N802
        return None

    def setDisplayFormat(self, fmt: str) -> None:  # noqa: N802
        current = self.getDate()
        if fmt and fmt.lower().startswith("mm"):
            self.setDateFormat(DatePicker.MM_DD_YYYY)
        else:
            self.setDateFormat(DatePicker.YYYY_MM_DD)
        if current.isValid():
            self.setDate(current)

    def setSpecialValueText(self, text: str) -> None:  # noqa: N802
        return None

    def setMinimumDate(self, date: QDate) -> None:  # noqa: N802
        return None

    def setMaximumDate(self, date: QDate) -> None:  # noqa: N802
        return None

    def setDateRange(self, minimum: QDate, maximum: QDate) -> None:  # noqa: N802
        return None


class TableWidget(_FluentTableWidget):
    def __init__(self, rows: int = 0, columns: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRowCount(rows)
        self.setColumnCount(columns)
        self.setShowGrid(False)
        if hasattr(self, "setBorderVisible"):
            self.setBorderVisible(False)


# Static enums/helpers remain available through the Qt base class.
TableWidgetItem = QTableWidgetItem
