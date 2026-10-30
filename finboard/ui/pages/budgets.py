"""Monthly spending budgets with live progress."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import days_in_month, month_label, month_of, today
from ...core.models import BudgetLine
from ...i18n import category_display, t
from ..dialogs import BudgetDialog
from ..theme import colors, tone_for_ratio
from ..widgets import (
    Badge,
    Card,
    ConfirmDialog,
    Dot,
    EmptyState,
    IconButton,
    MonthCombo,
    Page,
    PageHeader,
    ThemedButton,
    ValueLabel,
    clear_layout,
    progress_bar,
    set_progress,
)
from .components import StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


class BudgetRow(QFrame):
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(
        self, line: BudgetLine, service, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.line = line
        self.setObjectName("ListRow")
        self.setMinimumHeight(78)
        palette = colors()
        tone = tone_for_ratio(line.ratio * 100)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 10, 4, 10)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(9)
        top.addWidget(Dot(line.color, 9))
        name = QLabel(category_display(line.name))
        name.setProperty("i18nSkip", True)
        name.setStyleSheet("font-weight: 600;")
        top.addWidget(name)
        top.addStretch(1)
        percent = Badge(f"{line.ratio * 100:.0f}%", tone)
        top.addWidget(percent)
        edit = IconButton("edit", t("编辑预算"), size=15)
        delete = IconButton("trash", t("删除预算"), size=15)
        for button in (edit, delete):
            button.setFixedSize(28, 28)
            top.addWidget(button)
        edit.clicked.connect(lambda: self.edit_requested.emit(line))
        delete.clicked.connect(lambda: self.delete_requested.emit(line))
        outer.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bar = progress_bar(0)
        bar.setFixedHeight(6)
        set_progress(bar, line.ratio * 100, force_tone=tone if line.ratio > 0.8 else None)
        bottom.addWidget(bar, 1)
        used = QLabel(f"{service.format(line.spent)} / {service.format(line.amount)}")
        used.setProperty("role", "muted")
        used.setStyleSheet("font-size: 11px;")
        used.setFixedWidth(142)
        used.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(used)
        remaining = line.remaining
        left = QLabel(
            t("超支 {amount}", amount=service.format(-remaining))
            if remaining < 0
            else t("剩余 {amount}", amount=service.format(remaining))
        )
        left.setProperty("role", "danger" if remaining < 0 else "muted")
        left.setStyleSheet("font-size: 11px;")
        left.setFixedWidth(150)
        left.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom.addWidget(left)
        outer.addLayout(bottom)


class BudgetsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("预算", "给每个月的支出设一条安全线")
        self.month_combo = MonthCombo(count=24)
        self.month_combo.set_month(month_of(today()))
        self.month_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        header.add_action(self.month_combo)
        add_button = ThemedButton("设置预算", "primary", "plus")
        add_button.clicked.connect(self._add)
        header.add_action(add_button)
        self.header = header
        self.body.addWidget(header)

        self.stats = QHBoxLayout()
        self.stats.setSpacing(14)
        self.used_card = StatCard("已用预算", "expense", tone="expense")
        self.remain_card = StatCard("剩余预算", "savings", tone="income")
        self.rate_card = StatCard("使用率", "target", tone="primary")
        for card in (self.used_card, self.remain_card, self.rate_card):
            self.stats.addWidget(card, 1)
        self.body.addLayout(self.stats)

        self.hero = Card(padding=22, spacing=14)
        self.hero_body = QVBoxLayout()
        self.hero_body.setSpacing(12)
        self.hero.body.addLayout(self.hero_body)
        self.body.addWidget(self.hero)

        self.alert = QFrame()
        self.alert.setObjectName("SoftCard")
        alert_layout = QHBoxLayout(self.alert)
        alert_layout.setContentsMargins(16, 12, 16, 12)
        alert_layout.setSpacing(10)
        alert_icon = QLabel("!")
        alert_icon.setFixedSize(20, 20)
        alert_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alert_icon.setStyleSheet(
            f"background: {colors().warning_soft}; color: {colors().warning};"
            "border-radius: 10px; font-weight: 700;"
        )
        alert_layout.addWidget(alert_icon)
        self.alert_label = QLabel()
        self.alert_label.setWordWrap(True)
        self.alert_label.setProperty("role", "warning")
        alert_layout.addWidget(self.alert_label, 1)
        self.alert.hide()
        self.body.addWidget(self.alert)

        self.list_card = Card(padding=18, spacing=10)
        add_category = ThemedButton("添加分类预算", "soft", "plus")
        add_category.clicked.connect(self._add)
        self.list_card.add_header("分类预算", "按分类单独设限", add_category)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.list_card.body.addLayout(self.list_layout)
        self.body.addWidget(self.list_card)
        self.body.addStretch(1)

    # ------------------------------------------------------------------
    @property
    def month(self) -> str:
        return self.month_combo.current_month() or month_of(today())

    def refresh(self) -> None:
        month = self.month
        lines = self.service.repo.budget_lines(month)
        total = next((line for line in lines if line.is_overall), None)
        categories = [line for line in lines if not line.is_overall]
        self.header.set_subtitle(
            f"{month_label(month)} · {t('给支出设一条安全线')}"
        )

        self._rebuild_hero(total)
        self._rebuild_stats(total)
        self._rebuild_list(categories)
        self._rebuild_alert(total, categories)

    def _rebuild_hero(self, total: BudgetLine | None) -> None:
        clear_layout(self.hero_body)
        if total is None:
            self.hero_body.addWidget(
                EmptyState(
                    "target",
                    t("这个月还没有总预算"),
                    t("先设一个月度上限，再按分类拆分，超支时就能及时看到。"),
                    t("设置本月预算"),
                    self._add,
                )
            )
            return

        top = QHBoxLayout()
        title = QLabel(t("本月总预算"))
        title.setProperty("role", "cardTitle")
        top.addWidget(title)
        top.addStretch(1)
        status = Badge(
            t("预算健康") if total.ratio <= 1 else t("已超支"),
            "success" if total.ratio <= 1 else "danger",
        )
        top.addWidget(status)
        self.hero_body.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(20)
        amount = ValueLabel(self.service.format(total.amount), tone="text", size=34, weight=700)
        row.addWidget(amount)
        hint_column = QVBoxLayout()
        hint_column.setSpacing(2)
        used = QLabel(t("已用 {amount}", amount=self.service.format(total.spent)))
        used.setProperty("role", "muted")
        hint_column.addWidget(used)
        remaining = total.remaining
        if remaining < 0:
            detail = t("超出预算 {amount}", amount=self.service.format(-remaining))
            detail_role = "danger"
        else:
            detail = t("还可花 {amount}", amount=self.service.format(remaining))
            detail_role = "success"
        detail_label = QLabel(detail)
        detail_label.setProperty("role", detail_role)
        hint_column.addWidget(detail_label)
        row.addLayout(hint_column)
        row.addStretch(1)

        if month_of(today()) == total.month and total.remaining > 0:
            days_left = max(1, days_in_month(total.month) - today().day + 1)
            daily = QLabel(
                t(
                    "剩余 {days} 天 · 日均可用 {amount}",
                    days=days_left,
                    amount=self.service.format(total.remaining // days_left),
                )
            )
            daily.setProperty("role", "faint")
            row.addWidget(daily, 0, Qt.AlignmentFlag.AlignBottom)
        self.hero_body.addLayout(row)

        bar = progress_bar(total.ratio * 100)
        bar.setFixedHeight(10)
        bar.setTextVisible(False)
        set_progress(bar, total.ratio * 100)
        self.hero_body.addWidget(bar)

    def _rebuild_stats(self, total: BudgetLine | None) -> None:
        if total is None:
            self.used_card.set_value(
                self.service.format(0), hint=t("尚未设置预算"), tone="text"
            )
            self.remain_card.set_value(
                self.service.format(0), hint="—", tone="text"
            )
            self.rate_card.set_value("0%", hint=t("预算使用率"), tone="text")
            return
        self.used_card.set_value(
            self.service.format(total.spent),
            hint=t("预算 {amount}", amount=self.service.format(total.amount)),
            tone="expense",
        )
        if total.remaining < 0:
            self.remain_card.set_value(
                self.service.format(total.remaining),
                hint=t("已超出总预算"),
                tone="expense",
            )
        else:
            self.remain_card.set_value(
                self.service.format(total.remaining),
                hint=t("尚可支出"),
                tone="income",
            )
        self.rate_card.set_value(
            f"{total.ratio * 100:.0f}%",
            hint=t("已用 / 总预算"),
            tone="danger" if total.ratio > 1 else ("warning" if total.ratio > 0.8 else "primary"),
        )

    def _rebuild_list(self, categories: list[BudgetLine]) -> None:
        clear_layout(self.list_layout)
        if not categories:
            self.list_layout.addWidget(
                EmptyState(
                    "target",
                    t("还没有分类预算"),
                    t("给餐饮、购物等分类设上限，比只看总额更容易控制。"),
                    t("添加分类预算"),
                    self._add,
                )
            )
            return
        for line in categories:
            row = BudgetRow(line, self.service)
            row.edit_requested.connect(self._edit)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)

    def _rebuild_alert(
        self, total: BudgetLine | None, categories: list[BudgetLine]
    ) -> None:
        over = [line for line in categories if line.ratio > 1]
        if total is not None and total.ratio > 1:
            over.insert(0, total)
        if not over:
            self.alert.hide()
            return
        names = t("、").join(category_display(line.name) for line in over[:3])
        if len(over) > 3:
            names += t(" 等 {count} 项", count=len(over))
        self.alert_label.setText(
            t(
                "{names} 已超出预算，建议检查最近的支出。",
                names=names,
            )
        )
        self.alert.show()

    # ------------------------------------------------------------------
    def _add(self) -> None:
        BudgetDialog(self.service, self.month, parent=self.window).exec()

    def _edit(self, line: BudgetLine) -> None:
        BudgetDialog(self.service, self.month, line=line, parent=self.window).exec()

    def _delete(self, line: BudgetLine) -> None:
        if not ConfirmDialog.confirm(
            self,
            t("删除这条预算？"),
            t(
                "将删除「{name}」在 {month} 的预算，不会影响交易记录。",
                name=category_display(line.name),
                month=month_label(line.month),
            ),
            ok_text=t("删除"),
            danger=True,
            icon_name="trash",
        ):
            return
        self.service.delete_budget(line.id)
        self.window.notify(
            t("已删除「{name}」预算", name=category_display(line.name))
        )
