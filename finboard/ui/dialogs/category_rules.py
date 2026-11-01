"""Automatic category rules: payee keyword to category and tags."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.models import CategoryRule
from ...core.service import FinanceService
from ...i18n import t
from ..widgets import (
    ConfirmDialog,
    EmptyState,
    IconButton,
    SegmentedControl,
    ThemedButton,
    clear_layout,
)
from .common import dialog_header, root_layout


class CategoryRuleRow(QFrame):
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, rule: CategoryRule, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rule = rule
        self.setObjectName("ListRow")
        self.setMinimumHeight(64)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel(f"「{rule.pattern}」 → {rule.category_name}")
        title.setStyleSheet("font-weight: 600;")
        text.addWidget(title)
        pieces = [t("支出") if rule.kind == "expense" else t("收入")]
        if rule.tags:
            pieces.append(t("标签：{tags}", tags=rule.tag_text))
        pieces.append(t("命中 {count} 次", count=rule.hit_count))
        detail = QLabel(" · ".join(pieces))
        detail.setProperty("role", "faint")
        detail.setWordWrap(True)
        text.addWidget(detail)
        row.addLayout(text, 1)

        edit = IconButton("edit", "编辑规则", size=15)
        delete = IconButton("trash", "删除规则", size=15)
        for button in (edit, delete):
            button.setFixedSize(28, 28)
            row.addWidget(button)
        edit.clicked.connect(lambda: self.edit_requested.emit(rule))
        delete.clicked.connect(lambda: self.delete_requested.emit(rule))


class CategoryRulesDialog(QDialog):
    def __init__(self, service: FinanceService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._editing_id: int | None = None
        self.setWindowTitle(t("自动分类规则"))
        self.setModal(True)
        self.setMinimumSize(620, 660)
        self.resize(680, 760)

        layout = root_layout(self)
        header, _ = dialog_header(
            "自动分类规则",
            "付款对象包含关键词时，自动填充分类与标签。",
            "sparkles",
        )
        layout.addLayout(header)

        form = QFrame()
        form.setObjectName("Card")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(10)

        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText(t("付款对象包含的关键词，例如：星巴克"))
        self.pattern_input.setMaxLength(40)
        form_layout.addWidget(self.pattern_input)

        selector = QHBoxLayout()
        selector.setSpacing(10)
        self.kind_control = SegmentedControl(
            [("支出", "expense"), ("收入", "income")], "expense"
        )
        self.kind_control.setFixedWidth(190)
        self.kind_control.changed.connect(lambda _value: self._load_categories())
        selector.addWidget(self.kind_control)

        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(220)
        self.category_combo.setProperty("i18nSkip", True)
        selector.addWidget(self.category_combo, 1)
        form_layout.addLayout(selector)

        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText(t("可选标签，用逗号分隔，例如：咖啡,常去"))
        self.tags_input.setMaxLength(120)
        form_layout.addWidget(self.tags_input)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.save_button = ThemedButton("添加规则", "primary", "plus")
        self.save_button.clicked.connect(self._save)
        self.cancel_button = ThemedButton("取消编辑", "ghost")
        self.cancel_button.clicked.connect(self._reset_form)
        self.cancel_button.hide()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch(1)
        form_layout.addLayout(buttons)
        layout.addWidget(form)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 1)

        self.status = QLabel()
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.setSpacing(10)
        learn = ThemedButton("从历史学习", "soft", "sparkles")
        learn.clicked.connect(self._learn)
        backfill = ThemedButton("回填标签", "ghost", "tag")
        backfill.clicked.connect(self._backfill)
        footer.addWidget(learn)
        footer.addWidget(backfill)
        footer.addStretch(1)
        done = ThemedButton("完成", "secondary")
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        layout.addLayout(footer)

        self.service.changed.connect(self._reload)
        self._load_categories()
        self._reload()

    @property
    def kind(self) -> str:
        return self.kind_control.value() or "expense"

    def _load_categories(self, select_id: int | None = None) -> None:
        current = select_id if select_id is not None else self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for category in self.service.repo.categories(self.kind):
            self.category_combo.addItem(category.name, category.id)
        if current is not None:
            index = self.category_combo.findData(int(current))
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)

    def _reload(self) -> None:
        clear_layout(self.list_layout)
        rules = self.service.category_rules()
        if not rules:
            self.list_layout.addWidget(
                EmptyState(
                    "sparkles",
                    "还没有自动分类规则",
                    "添加关键词规则，或从历史记录中学习常用付款对象。",
                    "从历史学习",
                    self._learn,
                )
            )
            self.list_layout.addStretch(1)
            return
        for rule in rules:
            row = CategoryRuleRow(rule)
            row.edit_requested.connect(self._edit)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)
        self.list_layout.addStretch(1)

    def _parse_tags(self) -> list[str]:
        raw = self.tags_input.text().replace("，", ",").replace("、", ",")
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _save(self) -> None:
        pattern = self.pattern_input.text().strip()
        if not pattern:
            self._note("请填写付款对象关键词")
            self.pattern_input.setFocus()
            return
        category_id = self.category_combo.currentData()
        if not category_id:
            self._note("请先选择一个分类")
            return
        tags = self._parse_tags()
        try:
            if self._editing_id is None:
                self.service.add_category_rule(pattern, self.kind, category_id, tags)
                self._note("规则已添加")
            else:
                self.service.update_category_rule(
                    self._editing_id,
                    pattern=pattern,
                    category_id=category_id,
                    tags=tags,
                )
                self._note("规则已更新")
        except ValueError as exc:
            self._note(str(exc))
            return
        self._reset_form()

    def _edit(self, rule: CategoryRule) -> None:
        self._editing_id = rule.id
        self.pattern_input.setText(rule.pattern)
        self.kind_control.set_value(rule.kind)
        self.kind_control.setEnabled(False)
        self._load_categories(rule.category_id)
        self.tags_input.setText("、".join(rule.tags))
        self.save_button.setText(t("保存修改"))
        self.cancel_button.show()
        self.pattern_input.setFocus()

    def _reset_form(self) -> None:
        self._editing_id = None
        self.pattern_input.clear()
        self.tags_input.clear()
        self.kind_control.setEnabled(True)
        self.save_button.setText(t("添加规则"))
        self.cancel_button.hide()
        self._load_categories()

    def _delete(self, rule: CategoryRule) -> None:
        if not ConfirmDialog.confirm(
            self,
            t("删除规则「{pattern}」？", pattern=rule.pattern),
            "已存在的交易不会被修改，只影响之后的自动填充。",
            ok_text="删除",
            danger=True,
            icon_name="trash",
        ):
            return
        self.service.delete_category_rule(rule.id)
        if self._editing_id == rule.id:
            self._reset_form()
        self._note("规则已删除")

    def _learn(self) -> None:
        if not ConfirmDialog.confirm(
            self,
            "从历史记录学习规则？",
            "同一付款对象至少出现两次且分类一致时，会自动创建规则。",
            ok_text="开始学习",
            icon_name="sparkles",
        ):
            return
        created = self.service.learn_category_rules()
        if created:
            self._note(t("已从历史记录学习 {created} 条规则", created=created))
        else:
            self._note("没有找到可学习的新规则")

    def _backfill(self) -> None:
        if not ConfirmDialog.confirm(
            self,
            "把规则标签回填到历史记录？",
            "会把规则中的标签合并到匹配的历史交易，不会修改分类。",
            ok_text="回填",
            icon_name="tag",
        ):
            return
        changed = self.service.apply_rule_tags_to_history()
        if changed:
            self._note(t("已为 {changed} 笔历史记录补充标签", changed=changed))
        else:
            self._note("没有需要补充标签的历史记录")

    def _note(self, text: str) -> None:
        self.status.setText(t(text))
        self.status.show()
        self._reload()
