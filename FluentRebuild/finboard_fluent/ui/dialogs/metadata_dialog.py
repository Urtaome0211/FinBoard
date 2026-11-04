"""Tags, splits and attachments for an existing transaction."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.money import format_cents, parse_amount
from ...i18n import t
from ..widgets import ConfirmDialog, ThemedButton
from .common import dialog_footer, dialog_header, error_label, root_layout, show_error


class MetadataDialog(QDialog):
    def __init__(self, service, transaction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.transaction = transaction
        self.setWindowTitle(t("标签、拆分与附件"))
        self.resize(700, 560)

        layout = root_layout(self)
        header, _ = dialog_header(
            t("标签、拆分与附件"),
            f"{transaction.date} · {transaction.title} · {service.format(transaction.amount)}",
            "tag",
        )
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_splits(), t("拆分"))
        tabs.addTab(self._build_tags(), t("标签"))
        tabs.addTab(self._build_attachments(), t("附件"))
        if transaction.kind == "transfer":
            tabs.setTabEnabled(0, False)
        layout.addWidget(tabs, 1)

        self.error = error_label()
        footer = dialog_footer(self, self.error, save_text="保存", cancel_text="关闭")
        save = footer.itemAt(footer.count() - 1).widget()
        save.clicked.connect(self._save)
        layout.addLayout(footer)

    # ------------------------------------------------------------------ splits
    def _build_splits(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(9)
        hint = QLabel(
            t("把一笔支出/收入拆到多个分类；拆分合计必须等于 {amount}。转账不能拆分。").format(
                amount=self.service.format(self.transaction.amount)
            )
        )
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.split_table = QTableWidget(0, 3)
        self.split_table.setHorizontalHeaderLabels([t("分类"), t("金额"), t("备注")])
        self.split_table.horizontalHeader().setStretchLastSection(True)
        self.split_table.setColumnWidth(0, 190)
        self.split_table.setColumnWidth(1, 120)
        self.split_table.verticalHeader().setVisible(False)
        self.split_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.split_table, 1)

        buttons = QHBoxLayout()
        add = ThemedButton("添加一行", "soft", "plus")
        add.clicked.connect(lambda: self._add_split_row())
        remove = ThemedButton("删除选中", "ghost", "trash")
        remove.clicked.connect(self._remove_split_row)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        self.split_total = QLabel()
        self.split_total.setProperty("role", "muted")
        buttons.addWidget(self.split_total)
        layout.addLayout(buttons)

        self.split_categories = self.service.repo.categories(
            kind=self.transaction.kind if self.transaction.kind != "transfer" else "expense"
        )
        for split in self.transaction.splits:
            self._add_split_row(
                split.category_id, format_cents(split.amount, ""), split.note
            )
        self._update_split_total()
        return page

    def _add_split_row(
        self, category_id: int | None = None, amount: str = "", note: str = ""
    ) -> None:
        row = self.split_table.rowCount()
        self.split_table.insertRow(row)
        combo = QComboBox()
        for category in self.split_categories:
            combo.addItem(category.name, category.id)
        if category_id is not None:
            index = combo.findData(category_id)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(self._update_split_total)
        self.split_table.setCellWidget(row, 0, combo)
        amount_item = QTableWidgetItem(amount)
        amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.split_table.setItem(row, 1, amount_item)
        self.split_table.setItem(row, 2, QTableWidgetItem(note))
        self._update_split_total()

    def _remove_split_row(self) -> None:
        row = self.split_table.currentRow()
        if row >= 0:
            self.split_table.removeRow(row)
            self._update_split_total()

    def _split_payload(self) -> list[tuple[int, int, str]]:
        payload = []
        for row in range(self.split_table.rowCount()):
            combo = self.split_table.cellWidget(row, 0)
            amount_item = self.split_table.item(row, 1)
            if combo is None or amount_item is None:
                continue
            text = amount_item.text().strip()
            if not text:
                continue
            payload.append(
                (
                    int(combo.currentData()),
                    parse_amount(text),
                    (self.split_table.item(row, 2).text() if self.split_table.item(row, 2) else ""),
                )
            )
        return payload

    def _update_split_total(self) -> None:
        try:
            total = sum(item[1] for item in self._split_payload()) if self.split_table.rowCount() else 0
        except ValueError:
            total = 0
        self.split_total.setText(t("合计 {amount}").format(amount=self.service.format(total)))

    # -------------------------------------------------------------------- tags
    def _build_tags(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        hint = QLabel(t("多个标签用逗号分隔，最多 20 个，每个不超过 20 字。"))
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText(t("例如：旅行, 报销, 家庭"))
        self.tags_input.setText(", ".join(tag.name for tag in self.transaction.tags))
        layout.addWidget(self.tags_input)
        existing = QLabel(t("已有标签：") + "、".join(tag.name for tag in self.service.tags()) if self.service.tags() else t("还没有标签"))
        existing.setProperty("role", "faint")
        existing.setWordWrap(True)
        layout.addWidget(existing)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- attachments
    def _build_attachments(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 12, 4, 4)
        hint = QLabel(t("附件会复制到本机数据目录，删除记录不会自动删除附件。"))
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.attachment_list = QListWidget()
        self.attachment_list.itemDoubleClicked.connect(self._open_attachment)
        layout.addWidget(self.attachment_list, 1)
        buttons = QHBoxLayout()
        add = ThemedButton("添加附件", "soft", "plus")
        add.clicked.connect(self._add_attachment)
        remove = ThemedButton("删除附件", "ghost", "trash")
        remove.clicked.connect(self._remove_attachment)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._reload_attachments()
        return page

    def _reload_attachments(self) -> None:
        self.attachment_list.clear()
        for attachment in self.service.attachments(self.transaction.id):
            item = QListWidgetItem(
                f"{attachment.filename}  ·  {attachment.size / 1024:.0f} KB"
            )
            item.setData(Qt.ItemDataRole.UserRole, attachment.id)
            item.setToolTip(t("双击打开"))
            self.attachment_list.addItem(item)

    def _add_attachment(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("选择附件"))
        if not path:
            return
        try:
            self.service.add_attachment(self.transaction.id, path)
        except (OSError, ValueError) as exc:
            show_error(self.error, str(exc))
            return
        self._reload_attachments()

    def _remove_attachment(self) -> None:
        item = self.attachment_list.currentItem()
        if not item:
            return
        attachment_id = int(item.data(Qt.ItemDataRole.UserRole))
        if not ConfirmDialog.confirm(
            self, t("删除附件"), t("只删除附件记录和副本，不影响原文件。"), danger=True
        ):
            return
        self.service.delete_attachment(attachment_id)
        self._reload_attachments()

    def _open_attachment(self, item: QListWidgetItem) -> None:
        attachment = next(
            (a for a in self.service.attachments(self.transaction.id) if a.id == item.data(Qt.ItemDataRole.UserRole)),
            None,
        )
        if attachment:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.attachment_file(attachment))))

    # -------------------------------------------------------------------- save
    def _save(self) -> None:
        try:
            if self.transaction.kind != "transfer":
                splits = self._split_payload()
                self.service.set_transaction_metadata(
                    self.transaction.id, splits=splits
                )
            tags = [
                item.strip()
                for item in self.tags_input.text().replace("，", ",").split(",")
                if item.strip()
            ]
            self.service.set_transaction_metadata(self.transaction.id, tags=tags)
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
