"""Manage the expense and income categories in one place."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import Category
from ...core.service import FinanceService
from ..widgets import (
    ConfirmDialog,
    Dot,
    EmptyState,
    IconButton,
    SegmentedControl,
    ThemedButton,
    clear_layout,
)
from .category_dialog import CategoryDialog
from .common import dialog_header, root_layout


class CategoryManageRow(QFrame):
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(
        self, category: Category, usage: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.category = category
        self.setObjectName("ListRow")
        self.setFixedHeight(56)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(10)
        row.addWidget(Dot(category.color, 10))
        name = QLabel(category.name)
        name.setStyleSheet("font-weight: 600;")
        row.addWidget(name)
        count = QLabel(f"{usage} 笔记录")
        count.setProperty("role", "faint")
        row.addWidget(count)
        row.addStretch(1)
        edit = IconButton("edit", "编辑分类", size=15)
        delete = IconButton("trash", "删除分类", size=15)
        for button in (edit, delete):
            button.setFixedSize(28, 28)
            row.addWidget(button)
        edit.clicked.connect(lambda: self.edit_requested.emit(category))
        delete.clicked.connect(lambda: self.delete_requested.emit(category))


class CategoryManagerDialog(QDialog):
    def __init__(self, service: FinanceService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("分类管理")
        self.setModal(True)
        self.setMinimumSize(520, 560)
        self.resize(540, 640)

        layout = root_layout(self)
        header, _ = dialog_header(
            "分类管理",
            "整理支出与收入分类；删除后记录会移到「其他」",
            "tag",
        )
        layout.addLayout(header)

        self.tabs = SegmentedControl(
            [("支出分类", "expense"), ("收入分类", "income")], "expense"
        )
        self.tabs.setMaximumWidth(280)
        self.tabs.changed.connect(lambda _value: self._reload())
        layout.addWidget(self.tabs)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 1)

        self.status = QLabel()
        self.status.setProperty("role", "muted")
        self.status.hide()
        layout.addWidget(self.status)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 8, 0, 0)
        footer.setSpacing(10)
        add_button = ThemedButton("新建分类", "primary", "plus")
        add_button.clicked.connect(self._add)
        footer.addWidget(add_button)
        footer.addStretch(1)
        done_button = ThemedButton("完成", "secondary")
        done_button.clicked.connect(self.accept)
        footer.addWidget(done_button)
        layout.addLayout(footer)

        self._reload()

    @property
    def kind(self) -> str:
        return self.tabs.value() or "expense"

    def _reload(self) -> None:
        clear_layout(self.list_layout)
        categories = self.service.repo.categories(self.kind)
        if not categories:
            self.list_layout.addWidget(
                EmptyState(
                    "tag",
                    "还没有分类",
                    "新建一个分类，记一笔时就能选到它。",
                    "新建分类",
                    self._add,
                )
            )
            self.list_layout.addStretch(1)
            return
        for category in categories:
            usage = self.service.repo.category_usage(category.id)
            row = CategoryManageRow(category, usage)
            row.edit_requested.connect(self._edit)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)
        self.list_layout.addStretch(1)

    def _add(self) -> None:
        dialog = CategoryDialog(
            self.service, default_kind=self.kind, parent=self
        )
        if dialog.exec():
            self._note("分类已创建")

    def _edit(self, category: Category) -> None:
        dialog = CategoryDialog(self.service, category, parent=self)
        if dialog.exec():
            self._note("分类已更新")

    def _delete(self, category: Category) -> None:
        if not ConfirmDialog.confirm(
            self,
            f"删除「{category.name}」？",
            "这个分类下的记录会移到「其他」，对应分类预算也会被删除。",
            ok_text="删除",
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            fallback = self.service.delete_category(category.id)
        except ValueError as exc:
            ConfirmDialog.alert(self, "无法删除分类", str(exc), icon_name="alert")
            return
        self._note(f"已删除「{category.name}」，相关记录已移到「{fallback}」")

    def _note(self, text: str) -> None:
        self.status.setText(text)
        self.status.show()
        self._reload()
