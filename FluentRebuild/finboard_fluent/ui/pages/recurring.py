"""Recurring transaction rules and their due occurrences."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.dates import day_label, today_iso
from ...i18n import t
from ..dialogs import RecurringDialog
from ..rows import ElidedLabel
from ..theme import colors
from ..widgets import (
    Badge,
    Card,
    ConfirmDialog,
    EmptyState,
    IconButton,
    Page,
    PageHeader,
    ThemedButton,
    ValueLabel,
    clear_layout,
    icon_label,
)
from .components import StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


def frequency_label(rule) -> str:
    if rule.frequency == "daily":
        return t("每天") if rule.interval_count == 1 else t("每 {n} 天", n=rule.interval_count)
    if rule.frequency == "weekly":
        return t("每周") if rule.interval_count == 1 else t("每 {n} 周", n=rule.interval_count)
    if rule.frequency == "monthly":
        return t("每月") if rule.interval_count == 1 else t("每 {n} 个月", n=rule.interval_count)
    return t("每年") if rule.interval_count == 1 else t("每 {n} 年", n=rule.interval_count)


class RecurringRow(QFrame):
    post_requested = Signal(object)
    edit_requested = Signal(object)
    toggle_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(
        self, rule, service, due: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.rule = rule
        self.setObjectName("ListRow")
        self.setFixedHeight(72)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(12)

        icon = icon_label(
            "calendar",
            colors().primary if rule.active else colors().muted,
            size=18,
            background=colors().primary_soft if rule.active else colors().surface_alt,
            box=34,
            radius=10,
        )
        row.addWidget(icon)

        column = QVBoxLayout()
        column.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(7)
        title = ElidedLabel(rule.name, size=13, weight=600)
        title.setProperty("i18nSkip", True)
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(60)
        title_row.addWidget(title)
        kind_text = {
            "expense": t("支出"),
            "income": t("收入"),
            "transfer": t("转账"),
        }.get(rule.kind, rule.kind)
        title_row.addWidget(Badge(kind_text, "primary" if rule.kind == "transfer" else "neutral"))
        if not rule.active:
            title_row.addWidget(Badge(t("已暂停"), "warning"))
        elif due:
            title_row.addWidget(Badge(t("待入账"), "danger"))
        title_row.addStretch(1)
        column.addLayout(title_row)

        subtitle = f"{frequency_label(rule)} · {rule.account_name}"
        if rule.kind == "transfer" and rule.to_account_name:
            subtitle += f" → {rule.to_account_name}"
        subtitle += f" · {t('下次 {date}', date=day_label(rule.next_date))}"
        detail = ElidedLabel(subtitle, role="muted", size=11, weight=400)
        detail.setProperty("i18nSkip", True)
        column.addWidget(detail)
        row.addLayout(column, 1)

        amount = ValueLabel(
            service.format_money(rule.amount, rule.currency),
            tone="expense" if rule.kind == "expense" else "income",
            size=13,
            weight=600,
        )
        amount.setMinimumWidth(105)
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(amount)

        actions = QHBoxLayout()
        actions.setSpacing(0)
        post = IconButton("check", t("确认入账"), size=16, parent=self)
        post.setVisible(due)
        post.clicked.connect(lambda: self.post_requested.emit(self.rule))
        edit = IconButton("edit", t("编辑规则"), size=16, parent=self)
        edit.clicked.connect(lambda: self.edit_requested.emit(self.rule))
        toggle = IconButton(
            "archive" if rule.active else "refresh",
            t("暂停规则") if rule.active else t("启用规则"),
            size=16,
            parent=self,
        )
        toggle.clicked.connect(lambda: self.toggle_requested.emit(self.rule))
        delete = IconButton("trash", t("删除规则"), size=16, parent=self)
        delete.clicked.connect(lambda: self.delete_requested.emit(self.rule))
        for button in (post, edit, toggle, delete):
            button.setFixedSize(28, 28)
            actions.addWidget(button)
        row.addLayout(actions)


class RecurringPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window
        self.header = PageHeader("定期交易", "到期提醒，确认后写入收支")
        add = ThemedButton("新建规则", "primary", "plus")
        add.clicked.connect(self._add)
        self.header.add_action(add)
        self.body.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.total_card = StatCard("规则总数", "calendar", tone="primary")
        self.active_card = StatCard("生效规则", "check", tone="income")
        self.due_card = StatCard("待入账", "clock", tone="warning")
        self.upcoming_card = StatCard("未来 7 天", "calendar", tone="accent")
        for card in (
            self.total_card,
            self.active_card,
            self.due_card,
            self.upcoming_card,
        ):
            stats.addWidget(card, 1)
        self.body.addLayout(stats)

        self.banner = QFrame()
        self.banner.setObjectName("SoftCard")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        banner_layout.setSpacing(12)
        banner_layout.addWidget(
            icon_label(
                "alert",
                colors().warning,
                size=18,
                background=colors().warning_soft,
                box=32,
                radius=9,
            )
        )
        self.banner_text = QLabel()
        self.banner_text.setProperty("role", "warning")
        self.banner_text.setWordWrap(True)
        banner_layout.addWidget(self.banner_text, 1)
        self.post_all = ThemedButton("全部入账", "soft", "check")
        self.post_all.clicked.connect(self._post_all)
        banner_layout.addWidget(self.post_all)
        self.banner.hide()
        self.body.addWidget(self.banner)

        self.list_card = Card(padding=18, spacing=6)
        self.count_label = QLabel("0")
        self.count_label.setProperty("role", "muted")
        self.list_card.add_header("所有规则", "按到期日排序", self.count_label)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.list_card.body.addLayout(self.list_layout)
        self.body.addWidget(self.list_card)
        self.body.addStretch(1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        rules = self.service.repo.recurring_rules()
        day = today_iso()
        due = [rule for rule in rules if rule.active and rule.next_date <= day]
        active = [rule for rule in rules if rule.active]
        horizon = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
        upcoming = [
            rule
            for rule in active
            if day < rule.next_date <= horizon
        ]
        self.total_card.set_value(str(len(rules)), hint="含已暂停的规则")
        self.active_card.set_value(str(len(active)), hint="正在生效")
        self.due_card.set_value(
            str(len(due)),
            hint="等待确认入账",
            tone="danger" if due else "text",
        )
        self.upcoming_card.set_value(str(len(upcoming)), hint="7 天内到期")
        self.count_label.setText(str(len(rules)))
        self.banner.setVisible(bool(due))
        self.banner_text.setText(
            t(
                "有 {count} 笔定期交易已到期，确认后才会写入收支。",
                count=len(due),
            )
        )
        self.post_all.setText(t("全部入账（{count}）", count=len(due)))

        clear_layout(self.list_layout)
        if not rules:
            self.list_layout.addWidget(
                EmptyState(
                    "calendar",
                    "还没有定期交易",
                    "把房租、工资、会员费等固定收支设成规则，到期时只需确认。",
                    "新建规则",
                    self._add,
                )
            )
            return
        for rule in sorted(rules, key=lambda item: (not item.active, item.next_date)):
            row = RecurringRow(rule, self.service, rule.active and rule.next_date <= day)
            row.post_requested.connect(self._post)
            row.edit_requested.connect(self._edit)
            row.toggle_requested.connect(self._toggle)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)

    # ------------------------------------------------------------------
    def _add(self) -> None:
        RecurringDialog(self.service, parent=self.window).exec()

    def _edit(self, rule) -> None:
        RecurringDialog(self.service, rule, parent=self.window).exec()

    def _post(self, rule) -> None:
        try:
            self.service.post_recurring(rule.id)
        except ValueError as exc:
            ConfirmDialog.alert(self, t("无法入账"), str(exc), icon_name="alert")
            return
        self.window.notify(t("已入账「{name}」", name=rule.name))

    def _post_all(self) -> None:
        day = today_iso()
        count = 0
        try:
            for rule in self.service.repo.due_recurring(day):
                for _ in range(120):
                    current = self.service.repo.get_recurring(rule.id)
                    if not current.active or current.next_date > day:
                        break
                    self.service.post_recurring(rule.id)
                    count += 1
        except ValueError as exc:
            ConfirmDialog.alert(self, t("无法入账"), str(exc), icon_name="alert")
        if count:
            self.window.notify(t("已入账 {count} 笔定期交易", count=count))

    def _toggle(self, rule) -> None:
        self.service.set_recurring_active(rule.id, not rule.active)
        self.window.notify(
            t("已恢复「{name}」", name=rule.name)
            if not rule.active
            else t("已暂停「{name}」", name=rule.name)
        )

    def _delete(self, rule) -> None:
        if not ConfirmDialog.confirm(
            self,
            t("删除这条规则？"),
            t("「{name}」删除后不会再生成新的入账提醒，已入账的交易会保留。", name=rule.name),
            ok_text=t("删除"),
            danger=True,
            icon_name="trash",
        ):
            return
        self.service.delete_recurring(rule.id)
        self.window.notify(t("已删除规则「{name}」", name=rule.name))
