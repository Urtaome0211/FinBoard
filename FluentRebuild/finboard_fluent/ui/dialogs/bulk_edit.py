"""Batch category/tag editing for the transaction table."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit

from ...core.service import FinanceService
from ...i18n import category_display, t
from ..widgets import ComboBox
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class BulkEditDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        transaction_ids: list[int],
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.transaction_ids = transaction_ids
        count = len(transaction_ids)
        self.result = None
        self.setWindowTitle(t("批量编辑"))
        self.setMinimumWidth(500)
        root = root_layout(self)
        header, _ = dialog_header(
            t("批量编辑"),
            t("已选择 {count} 笔交易；只修改填写的字段").format(count=count),
            "edit",
        )
        root.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        self.category_combo = ComboBox()
        self.category_combo.addItem(t("不修改分类"), None)
        for kind in ("expense", "income"):
            for category in service.repo.categories(kind):
                self.category_combo.addItem(
                    f"{category_display(category.name)} · {t('支出' if kind == 'expense' else '收入')}",
                    category.id,
                )
        self.add_tags = QLineEdit()
        self.add_tags.setPlaceholderText(t("逗号分隔，例如：旅行, 报销"))
        self.remove_tags = QLineEdit()
        self.remove_tags.setPlaceholderText(t("逗号分隔；只移除已有标签"))
        form.addRow(form_label(t("分类")), self.category_combo)
        form.addRow(form_label(t("添加标签")), self.add_tags)
        form.addRow(form_label(t("移除标签")), self.remove_tags)
        root.addLayout(form)

        note = QLabel(t("转账、已拆分交易或收支类型不匹配的交易会被跳过。"))
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        root.addWidget(note)
        self.error = error_label()
        root.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("应用到所选交易"), cancel_text=t("取消")
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        root.addLayout(footer)

    @staticmethod
    def _tags(text: str) -> list[str]:
        return [
            part.strip()
            for part in text.replace("，", ",").split(",")
            if part.strip()
        ]

    def _save(self) -> None:
        category_id = self.category_combo.currentData()
        add_tags = self._tags(self.add_tags.text())
        remove_tags = self._tags(self.remove_tags.text())
        if category_id is None and not add_tags and not remove_tags:
            show_error(self.error, t("请至少选择分类或填写标签"))
            return
        self.result = self.service.bulk_update_transactions(
            self.transaction_ids,
            category_id=category_id,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )
        if not self.result.updated:
            show_error(self.error, t("没有可更新的交易"))
            return
        self.accept()
