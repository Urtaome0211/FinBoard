"""Data health checks: duplicates, uncategorized rows and stale items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...i18n import t
from ..theme import colors
from ..widgets import Badge, Card, Page, PageHeader, ThemedButton, clear_layout, icon_label

if TYPE_CHECKING:
    from ..main_window import MainWindow


class HealthPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("数据体检", "找出重复记录、漏分类与需要跟进的条目")
        refresh = ThemedButton("重新检查", "secondary", "refresh")
        refresh.clicked.connect(self.refresh)
        header.add_action(refresh)
        self.header = header
        self.body.addWidget(header)

        self.summary_card = Card(padding=22, spacing=8)
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.summary_hint = QLabel()
        self.summary_hint.setProperty("role", "muted")
        self.summary_card.body.addWidget(self.summary_label)
        self.summary_card.body.addWidget(self.summary_hint)
        self.body.addWidget(self.summary_card)

        self.list_card = Card(padding=18, spacing=6)
        self.list_card.add_header("检查项", "点击「去处理」跳转到对应页面")
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(4)
        self.list_card.body.addLayout(self.list_layout)
        self.body.addWidget(self.list_card)
        self.body.addStretch(1)

    def refresh(self) -> None:
        checks = self.service.health_checks()
        total = sum(int(item.get("count", 0)) for item in checks)
        self.summary_label.setText(
            t("发现 {count} 处待处理", count=total) if total else t("账本状态良好")
        )
        self.summary_hint.setText(
            t("体检只读取数据，不会自动修改任何记录。")
        )
        clear_layout(self.list_layout)
        palette = colors()
        for check in checks:
            count = int(check.get("count", 0))
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(4, 10, 4, 10)
            layout.setSpacing(12)
            tone = "success" if count == 0 else ("danger" if check.get("level") == "danger" else "warning")
            color = palette.income if count == 0 else (
                palette.expense if tone == "danger" else palette.warning
            )
            layout.addWidget(icon_label("check" if count == 0 else "alert", color, 16, palette.surface_alt, box=32, radius=9))
            text = QVBoxLayout()
            text.setSpacing(2)
            title = QLabel(str(check.get("label", "")))
            title.setStyleSheet("font-weight: 600;")
            text.addWidget(title)
            hint = QLabel(str(check.get("hint", "")))
            hint.setProperty("role", "faint")
            hint.setWordWrap(True)
            text.addWidget(hint)
            layout.addLayout(text, 1)
            layout.addWidget(Badge(t("正常") if count == 0 else t("{count} 项", count=count), tone))
            link = str(check.get("link", ""))
            if count and link in self.window.pages:
                action = ThemedButton("去处理", "ghost")
                action.clicked.connect(lambda _checked=False, key=link: self.window.navigate(key))
                layout.addWidget(action)
            self.list_layout.addWidget(row)
