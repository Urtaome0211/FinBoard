"""Translate an existing widget tree in place.

The app is written with Chinese source strings.  Keeping the source readable
and translating at the widget boundary avoids threading a translation call
through every layout statement, while still giving an immediate language
switch after the main window is rebuilt.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QLocale, QObject, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QTabWidget,
    QWidget,
)

from ..i18n import is_english, t


def apply_locale() -> None:
    """Make Qt's calendar/popup locale match the UI language."""
    locale = (
        QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        if is_english()
        else QLocale(QLocale.Language.Chinese, QLocale.Country.China)
    )
    QLocale.setDefault(locale)


def _translated(text: str) -> str:
    return t(text) if text else text


def _skipped(widget: QWidget) -> bool:
    node: QWidget | None = widget
    while node is not None:
        if node.property("i18nSkip"):
            return True
        node = node.parentWidget()
    return False


def localize_widgets(root: QWidget) -> None:
    """Translate labels, buttons, hints and tooltips below *root*."""
    if not is_english():
        return

    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if _skipped(widget):
            continue
        if isinstance(widget, QWidget) and widget.windowTitle():
            widget.setWindowTitle(_translated(widget.windowTitle()))

        if isinstance(widget, QLabel):
            widget.setText(_translated(widget.text()))
        elif isinstance(widget, QAbstractButton):
            widget.setText(_translated(widget.text()))
        elif isinstance(widget, QGroupBox):
            widget.setTitle(_translated(widget.title()))
        elif isinstance(widget, QLineEdit):
            widget.setPlaceholderText(_translated(widget.placeholderText()))
        elif isinstance(widget, QComboBox):
            _localize_combo(widget)
        elif isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                widget.setTabText(index, _translated(widget.tabText(index)))
        elif isinstance(widget, QMenu):
            for action in widget.actions():
                if action.text():
                    action.setText(_translated(action.text()))
                if action.toolTip():
                    action.setToolTip(_translated(action.toolTip()))

        if widget.toolTip():
            widget.setToolTip(_translated(widget.toolTip()))
        if isinstance(widget, QMenu):
            for action in widget.actions():
                if action.statusTip():
                    action.setStatusTip(_translated(action.statusTip()))


def _localize_combo(combo: QComboBox) -> None:
    for index in range(combo.count()):
        text = combo.itemText(index)
        translated = _translated(text)
        if translated != text:
            combo.setItemText(index, translated)


class _LocaleFilter(QObject):
    """Localize dialogs/menus just before they become visible."""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(obj, (QDialog, QMenu)):
            QTimer.singleShot(0, lambda target=obj: localize_widgets(target))
        return False


def install_localizer(app) -> None:
    if getattr(app, "_finboard_localizer", None) is not None:
        return
    watcher = _LocaleFilter(app)
    app._finboard_localizer = watcher
    app.installEventFilter(watcher)
