"""Flat visual language: palettes, Qt palette and the global stylesheet."""

from __future__ import annotations

from dataclasses import dataclass
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..core.paths import resource_path


@dataclass(frozen=True)
class Palette:
    mode: str
    bg: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_soft: str
    income: str
    income_soft: str
    expense: str
    expense_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    accent: str
    accent_soft: str
    info: str
    info_soft: str
    chart_grid: str
    selection: str
    sidebar: str
    scrollbar: str
    scrollbar_hover: str
    tooltip_bg: str
    tooltip_text: str


LIGHT = Palette(
    mode="light",
    bg="#F5F7FB",
    surface="#FFFFFF",
    surface_alt="#F8FAFD",
    surface_hover="#F0F4FA",
    border="#E8EDF5",
    border_strong="#D8E1EE",
    text="#172033",
    muted="#667085",
    faint="#98A2B3",
    primary="#3D6DF2",
    primary_hover="#2F5EE0",
    primary_pressed="#2855CC",
    primary_soft="#EBF1FE",
    income="#159A6C",
    income_soft="#E7F7F0",
    expense="#E5484D",
    expense_soft="#FDECEC",
    warning="#D98E1F",
    warning_soft="#FDF4E3",
    danger="#D93A3F",
    danger_soft="#FDECEC",
    accent="#7C6CF2",
    accent_soft="#F0EDFE",
    info="#2D9CDB",
    info_soft="#E8F5FC",
    chart_grid="#EDF1F8",
    selection="#EAF1FF",
    sidebar="#FFFFFF",
    scrollbar="#D5DDEA",
    scrollbar_hover="#B8C4D8",
    tooltip_bg="#172033",
    tooltip_text="#FFFFFF",
)

DARK = Palette(
    mode="dark",
    bg="#0E1320",
    surface="#151C2B",
    surface_alt="#1A2233",
    surface_hover="#202A3D",
    border="#263248",
    border_strong="#34435C",
    text="#E9EEF8",
    muted="#A3B0C6",
    faint="#6F7F98",
    primary="#6E96FF",
    primary_hover="#86A8FF",
    primary_pressed="#5B84F0",
    primary_soft="#1E2C4F",
    income="#4BD39A",
    income_soft="#14332A",
    expense="#FF7B80",
    expense_soft="#3A1D24",
    warning="#F0B45A",
    warning_soft="#382B17",
    danger="#FF6B70",
    danger_soft="#3A1C21",
    accent="#A18CFF",
    accent_soft="#2A2547",
    info="#5CC0F0",
    info_soft="#16303F",
    chart_grid="#233048",
    selection="#22345A",
    sidebar="#121927",
    scrollbar="#2E3B52",
    scrollbar_hover="#41506B",
    tooltip_bg="#E9EEF8",
    tooltip_text="#101725",
)

THEMES = {"light": LIGHT, "dark": DARK}
THEME_LABELS = {"light": "浅色", "dark": "深色"}


class _ThemeStore(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mode = "light"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def colors(self) -> Palette:
        return THEMES[self._mode]

    def set_mode(self, mode: str) -> None:
        if mode not in THEMES:
            mode = "light"
        if mode != self._mode:
            self._mode = mode
            self.changed.emit()

    def toggle(self) -> str:
        self.set_mode("dark" if self._mode == "light" else "light")
        return self._mode


theme_store = _ThemeStore()


def colors() -> Palette:
    return theme_store.colors


def theme_mode() -> str:
    return theme_store.mode


def is_dark() -> bool:
    return theme_store.mode == "dark"


def tone_for_ratio(ratio: float) -> str:
    """Semantic colour for budget / limit progress."""
    if ratio >= 100:
        return "danger"
    if ratio >= 80:
        return "warning"
    return "success"


_QSS = Template(
    """
* {
    outline: none;
}
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: $text;
}
QMainWindow, QDialog {
    background-color: $bg;
}
QWidget#AppRoot {
    background-color: $bg;
}
QFrame#Sidebar {
    background-color: $sidebar;
    border: none;
    border-right: 1px solid $border;
}
QFrame#Topbar {
    background-color: $bg;
    border: none;
    border-bottom: 1px solid $border;
}
QFrame#Card, QFrame#StatCard {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 14px;
}
QFrame#SoftCard {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 12px;
}
QFrame#Divider {
    background-color: $border;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame#TxnRow, QFrame#AccountRow, QFrame#ListRow {
    background: transparent;
    border: none;
    border-bottom: 1px solid $border;
    border-radius: 0;
}
QFrame#TxnRow:hover, QFrame#AccountRow:hover, QFrame#ListRow:hover {
    background-color: $surface_hover;
}
QLabel {
    background: transparent;
    border: none;
}
QLabel[role="pageTitle"] {
    font-size: 26px;
    font-weight: 700;
    color: $text;
}
QLabel[role="dialogTitle"] {
    font-size: 19px;
    font-weight: 700;
    color: $text;
}
QLabel[role="pageSubtitle"] {
    font-size: 13px;
    color: $muted;
}
QLabel[role="sectionTitle"] {
    font-size: 17px;
    font-weight: 600;
    color: $text;
}
QLabel[role="cardTitle"] {
    font-size: 15px;
    font-weight: 600;
    color: $text;
}
QLabel[role="muted"] {
    color: $muted;
    font-size: 12px;
}
QLabel[role="faint"] {
    color: $faint;
    font-size: 12px;
}
QLabel[role="heroLabel"] {
    color: $muted;
    font-size: 13px;
}
QLabel[role="heroValue"] {
    color: $text;
    font-size: 38px;
    font-weight: 700;
}
QLabel[role="heroValueSmall"] {
    color: $text;
    font-size: 28px;
    font-weight: 700;
}
QLabel[role="statValue"] {
    color: $text;
    font-size: 24px;
    font-weight: 700;
}
QLabel[role="statLabel"] {
    color: $muted;
    font-size: 12px;
}
QLabel[role="incomeText"] {
    color: $income;
    font-weight: 600;
}
QLabel[role="expenseText"] {
    color: $expense;
    font-weight: 600;
}
QLabel[role="primaryText"] {
    color: $primary;
    font-weight: 600;
}
QFrame#Segment {
    background-color: $surface_alt;
    border: 1px solid $border;
    border-radius: 9px;
}
QPushButton#SegmentButton {
    min-height: 28px;
    padding: 0 14px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: $muted;
    font-weight: 500;
}
QPushButton#SegmentButton:hover {
    color: $text;
}
QPushButton#SegmentButton:checked {
    background-color: $surface;
    border: 1px solid $border_strong;
    color: $text;
    font-weight: 600;
}
QLabel[role="error"] {
    color: $danger;
    font-size: 12px;
}
QLabel[role="success"] {
    color: $income;
    font-size: 12px;
}
QLabel[role="warning"] {
    color: $warning;
    font-size: 12px;
}
QLabel[role="brandTitle"] {
    font-size: 18px;
    font-weight: 700;
    color: $text;
}
QLabel[role="brandSubtitle"] {
    font-size: 11px;
    color: $faint;
    letter-spacing: 1px;
}
QLabel[role="navSection"] {
    color: $faint;
    font-size: 11px;
    font-weight: 600;
}
QPushButton {
    min-height: 36px;
    padding: 0 16px;
    border-radius: 9px;
    border: 1px solid transparent;
    background: transparent;
    color: $text;
    font-weight: 500;
}
QPushButton:disabled {
    color: $faint;
    background-color: $surface_alt;
    border-color: $border;
}
QPushButton#PrimaryButton {
    background-color: $primary;
    color: #FFFFFF;
    border: 1px solid $primary;
}
QPushButton#PrimaryButton:hover {
    background-color: $primary_hover;
    border-color: $primary_hover;
}
QPushButton#PrimaryButton:pressed {
    background-color: $primary_pressed;
    border-color: $primary_pressed;
}
QPushButton#SecondaryButton {
    background-color: $surface;
    border: 1px solid $border_strong;
    color: $text;
}
QPushButton#SecondaryButton:hover {
    background-color: $surface_hover;
}
QPushButton#GhostButton {
    background: transparent;
    color: $muted;
    border: none;
}
QPushButton#GhostButton:hover {
    background-color: $surface_hover;
    color: $text;
}
QPushButton#DangerButton {
    background-color: $danger;
    border: 1px solid $danger;
    color: #FFFFFF;
}
QPushButton#DangerButton:hover {
    background-color: $expense;
    border-color: $expense;
}
QPushButton#SoftButton {
    background-color: $primary_soft;
    color: $primary;
    border: none;
}
QPushButton#SoftButton:hover {
    background-color: $selection;
}
QPushButton#LinkButton {
    background: transparent;
    border: none;
    color: $primary;
    padding: 0 4px;
    min-height: 24px;
}
QPushButton#LinkButton:hover {
    color: $primary_hover;
    text-decoration: underline;
}
QPushButton#IconButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0;
    border-radius: 9px;
    background: transparent;
    border: none;
}
QPushButton#IconButton:hover {
    background-color: $surface_hover;
}
QPushButton#NavButton {
    min-height: 42px;
    padding: 0 12px;
    border-radius: 10px;
    border: none;
    background: transparent;
    color: $muted;
    text-align: left;
    font-weight: 500;
}
QPushButton#NavButton:hover {
    background-color: $surface_hover;
    color: $text;
}
QPushButton#NavButton:checked {
    background-color: $primary_soft;
    color: $primary;
    font-weight: 600;
}
QPushButton#WinButton {
    min-width: 44px;
    max-width: 44px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    border: none;
    background: transparent;
    color: $muted;
    font-size: 14px;
}
QPushButton#WinButton:hover {
    background-color: $surface_hover;
    color: $text;
}
QLineEdit, QComboBox, QDateEdit, QDateTimeEdit {
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid $border_strong;
    border-radius: 9px;
    background-color: $surface;
    color: $text;
    selection-background-color: $primary_soft;
    selection-color: $text;
}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover {
    border-color: $faint;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus {
    border-color: $primary;
}
QLineEdit[invalid="true"], QComboBox[invalid="true"], QDateEdit[invalid="true"] {
    border-color: $danger;
}
QLineEdit#SearchInput {
    padding-left: 6px;
    background-color: $surface;
}
QLineEdit#AmountInput {
    min-height: 52px;
    font-size: 26px;
    font-weight: 700;
    padding: 0 14px;
    border-radius: 10px;
}
QComboBox {
    padding-right: 30px;
}
QComboBox::drop-down {
    border: none;
    width: 0;
}
QComboBox QAbstractItemView {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 4px;
    selection-background-color: $primary_soft;
    selection-color: $text;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 32px;
    padding: 0 10px;
    border-radius: 6px;
}
QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    background: transparent;
}
QDateEdit::down-arrow {
    image: url($chevron_icon);
    width: 12px;
    height: 12px;
}
QCheckBox {
    spacing: 8px;
    color: $text;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid $border_strong;
    background-color: $surface;
}
QCheckBox::indicator:hover {
    border-color: $primary;
}
QCheckBox::indicator:checked {
    background-color: $primary;
    border-color: $primary;
    image: url($check_icon);
}
QTableView, QTableWidget {
    background-color: $surface;
    alternate-background-color: $surface_alt;
    border: none;
    border-radius: 0 0 14px 14px;
    gridline-color: transparent;
    selection-background-color: $selection;
    selection-color: $text;
}
QTableView::item, QTableWidget::item {
    padding: 0 12px;
    border: none;
    border-bottom: 1px solid $border;
}
QTableView::item:selected, QTableWidget::item:selected {
    background-color: $selection;
    color: $text;
}
QHeaderView {
    background-color: $surface;
    border: none;
}
QHeaderView::section {
    background-color: $surface;
    color: $muted;
    font-size: 12px;
    font-weight: 600;
    padding: 0 12px;
    height: 40px;
    border: none;
    border-bottom: 1px solid $border;
}
QTableCornerButton::section {
    background-color: $surface;
    border: none;
}
QProgressBar {
    min-height: 8px;
    max-height: 8px;
    border: none;
    border-radius: 4px;
    background-color: $surface_alt;
    text-align: center;
}
QProgressBar::chunk {
    border-radius: 4px;
    background-color: $primary;
}
QProgressBar[tone="success"]::chunk {
    background-color: $income;
}
QProgressBar[tone="warning"]::chunk {
    background-color: $warning;
}
QProgressBar[tone="danger"]::chunk {
    background-color: $danger;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 9px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    min-height: 36px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: $scrollbar_hover;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 9px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar;
    min-width: 36px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}
QMenu {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    min-height: 32px;
    padding: 0 22px 0 14px;
    border-radius: 6px;
    color: $text;
}
QMenu::item:selected {
    background-color: $primary_soft;
    color: $text;
}
QMenu::item:disabled {
    color: $faint;
}
QToolTip {
    background-color: $tooltip_bg;
    color: $tooltip_text;
    border: none;
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 12px;
}
QDialog QLabel {
    color: $text;
}
QMessageBox {
    background-color: $surface;
}
QMessageBox QLabel {
    color: $text;
    font-size: 13px;
}
QCalendarWidget QWidget {
    background-color: $surface;
    color: $text;
}
QCalendarWidget QAbstractItemView {
    background-color: $surface;
    color: $text;
    selection-background-color: $primary;
    selection-color: #FFFFFF;
}
QCalendarWidget QTableView::item {
    padding: 0;
    border: none;
}
QCalendarWidget QToolButton {
    color: $text;
    background: transparent;
    border: none;
}
"""
)


def _asset_url(name: str) -> str:
    path = resource_path(name)
    return path.as_posix()


def build_qss() -> str:
    palette = colors()
    return _QSS.substitute(
        **{
            key: getattr(palette, key)
            for key in palette.__dataclass_fields__
            if key != "mode"
        },
        check_icon=_asset_url("check.svg"),
        chevron_icon=_asset_url("chevron-down.svg"),
    )


def build_palette(palette: Palette | None = None) -> QPalette:
    palette = palette or colors()
    result = QPalette()
    result.setColor(QPalette.ColorRole.Window, QColor(palette.bg))
    result.setColor(QPalette.ColorRole.WindowText, QColor(palette.text))
    result.setColor(QPalette.ColorRole.Base, QColor(palette.surface))
    result.setColor(QPalette.ColorRole.AlternateBase, QColor(palette.surface_alt))
    result.setColor(QPalette.ColorRole.Text, QColor(palette.text))
    result.setColor(QPalette.ColorRole.Button, QColor(palette.surface))
    result.setColor(QPalette.ColorRole.ButtonText, QColor(palette.text))
    result.setColor(QPalette.ColorRole.Highlight, QColor(palette.primary))
    result.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    result.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette.tooltip_bg))
    result.setColor(QPalette.ColorRole.ToolTipText, QColor(palette.tooltip_text))
    result.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(palette.faint)
    )
    result.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(palette.faint),
    )
    return result


def apply_theme(app: QApplication, mode: str | None = None) -> None:
    """Switch palette + stylesheet and notify custom-painted widgets."""
    if mode is not None:
        theme_store.set_mode(mode)
    app.setPalette(build_palette())
    app.setStyleSheet(build_qss())
    theme_store.changed.emit()
