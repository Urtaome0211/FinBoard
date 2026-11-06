"""Small Fluent text prompt used instead of QInputDialog."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout

from ...i18n import t
from ..fluent_controls import LineEdit
from ..widgets import ThemedButton
from .common import dialog_header, form_label, root_layout


class TextPromptDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        title: str,
        label: str,
        default: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = root_layout(self)
        header, _ = dialog_header(title, "", "edit")
        layout.addLayout(header)
        layout.addWidget(form_label(label))
        self.input = LineEdit(default)
        layout.addWidget(self.input)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch(1)
        cancel = ThemedButton(t("取消"), "secondary")
        cancel.clicked.connect(self.reject)
        save = ThemedButton(t("确定"), "primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)
        self.input.selectAll()
        self.input.setFocus()

    def value(self) -> str:
        return self.input.text().strip()


def ask_text(parent, *, title: str, label: str, default: str = "") -> tuple[str, bool]:
    dialog = TextPromptDialog(
        parent, title=title, label=label, default=default
    )
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.value(), True
    return "", False
