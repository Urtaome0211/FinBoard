"""CSV import dialog with column mapping and reusable rules."""

from __future__ import annotations
from ..fluent_controls import CheckBox, ComboBox, LineEdit, PushButton

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from ...core.csv_io import CSV_FIELDS
from ...i18n import t
from ..widgets import ConfirmDialog, ThemedButton
from .common import dialog_footer, dialog_header, error_label, root_layout, show_error

FIELD_LABELS = {
    "date": "日期",
    "kind": "类型",
    "amount": "金额",
    "currency": "币种",
    "category": "分类",
    "account": "账户",
    "to_account": "转入账户",
    "to_amount": "到账金额",
    "payee": "对方",
    "note": "备注",
}

IMPORT_PRESETS = {
    "alipay": {
        "label": "支付宝账单",
        "fields": {
            "date": ("交易时间", "交易创建时间", "时间"),
            "kind": ("收/支", "收／支"),
            "amount": ("金额", "金额(元)", "金额（元）"),
            "payee": ("交易对方", "对方"),
            "note": ("商品说明", "商品名称", "备注"),
            "account": ("收/付款方式", "支付方式"),
        },
    },
    "wechat": {
        "label": "微信支付账单",
        "fields": {
            "date": ("交易时间", "时间"),
            "kind": ("收/支", "收／支"),
            "amount": ("金额(元)", "金额（元）", "金额"),
            "payee": ("交易对方", "对方"),
            "note": ("商品", "商品说明", "备注"),
            "account": ("支付方式",),
        },
    },
    "bank": {
        "label": "银行流水",
        "fields": {
            "date": ("交易日期", "日期", "时间"),
            "kind": ("收支类型", "收/支", "类型"),
            "amount": ("交易金额", "金额", "金额(元)"),
            "payee": ("对方户名", "对方名称", "对方"),
            "note": ("摘要", "备注", "说明"),
            "account": ("账户", "付款账户", "交易账户"),
        },
    },
}


class CsvImportDialog(QDialog):
    def __init__(self, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.path: Path | None = None
        self.headers: list[str] = []
        self.rule_id: int | None = None
        self.setWindowTitle(t("导入 CSV"))
        self.resize(640, 620)

        layout = root_layout(self)
        header, _ = dialog_header(
            t("导入 CSV"),
            t("映射列、保存规则，重复记录会自动跳过"),
            "upload",
        )
        layout.addLayout(header)

        file_row = QHBoxLayout()
        self.file_label = QLabel(t("尚未选择文件"))
        self.file_label.setProperty("role", "muted")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        choose = ThemedButton("选择文件", "secondary", "upload")
        choose.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(choose)
        layout.addLayout(file_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(t("导入预设")))
        self.preset_combo = ComboBox()
        self.preset_combo.addItem(t("自动识别"), None)
        for key, preset in IMPORT_PRESETS.items():
            self.preset_combo.addItem(t(preset["label"]), key)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        preset_row.addWidget(self.preset_combo)
        preset_row.addSpacing(12)
        preset_row.addWidget(QLabel(t("默认账户")))
        self.default_account_combo = ComboBox()
        self.default_account_combo.addItem(t("使用文件中的账户"), None)
        for account in self.service.repo.accounts():
            self.default_account_combo.addItem(
                f"{account.name} · {account.currency}", account.id
            )
        preset_row.addWidget(self.default_account_combo, 1)
        layout.addLayout(preset_row)

        rule_row = QHBoxLayout()
        self.rule_combo = ComboBox()
        self.rule_combo.setMinimumWidth(150)
        self.rule_combo.currentIndexChanged.connect(self._rule_changed)
        self.name_input = LineEdit()
        self.name_input.setMinimumWidth(180)
        self.name_input.setPlaceholderText(t("规则名称，例如：招商银行账单"))
        save_rule = ThemedButton("保存为规则", "soft", "database")
        save_rule.clicked.connect(self._save_rule)
        delete_rule = ThemedButton("删除规则", "ghost", "trash")
        delete_rule.clicked.connect(self._delete_rule)
        rule_row.addWidget(self.rule_combo, 1)
        rule_row.addWidget(self.name_input, 1)
        rule_row.addWidget(save_rule)
        rule_row.addWidget(delete_rule)
        layout.addLayout(rule_row)

        self.mapping_widget = QWidget()
        columns = QHBoxLayout(self.mapping_widget)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(24)
        self.mapping_combos: dict[str, ComboBox] = {}
        for column_index, fields in enumerate((CSV_FIELDS[:5], CSV_FIELDS[5:])):
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            for field in fields:
                combo = ComboBox()
                combo.addItem(t("（不使用）"), "")
                combo.setMinimumWidth(205)
                form.addRow(t(FIELD_LABELS[field]), combo)
                self.mapping_combos[field] = combo
            columns.addLayout(form, 1)
        layout.addWidget(self.mapping_widget)

        self.dedup_check = CheckBox(t("跳过重复记录（按日期、类型、金额、账户、对方）"))
        self.dedup_check.setChecked(True)
        layout.addWidget(self.dedup_check)

        self.hint = QLabel(t("选择文件后核对列映射；分类和账户按名称匹配"))
        self.hint.setProperty("role", "muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.error = error_label()
        footer = dialog_footer(self, self.error, save_text="导入", cancel_text="取消")
        self.import_button = footer.itemAt(footer.count() - 1).widget()
        self.import_button.clicked.connect(self._import)
        layout.addLayout(footer)

        self._reload_rules()
        self._set_rule(None)

    # ------------------------------------------------------------------ rules
    def _reload_rules(self) -> None:
        current = self.rule_combo.currentData() if self.rule_combo.count() else None
        self.rule_combo.blockSignals(True)
        self.rule_combo.clear()
        self.rule_combo.addItem(t("自动识别（不保存规则）"), None)
        for rule in self.service.csv_rules():
            self.rule_combo.addItem(rule.name, rule.id)
        index = self.rule_combo.findData(current)
        self.rule_combo.setCurrentIndex(max(0, index))
        self.rule_combo.blockSignals(False)

    def _rule_changed(self) -> None:
        rule_id = self.rule_combo.currentData()
        self.rule_id = int(rule_id) if rule_id is not None else None
        if self.rule_id is None:
            self._set_rule(None)
            return
        rule = self.service.repo.get_csv_rule(self.rule_id)
        self.name_input.setText(rule.name)
        self.dedup_check.setChecked(rule.dedup)
        self._set_rule(rule.mapping)

    def _set_rule(self, mapping: dict[str, str] | None) -> None:
        for field, combo in self.mapping_combos.items():
            value = (mapping or {}).get(field, "")
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else 0)

    def _selected_mapping(self) -> dict[str, str]:
        return {
            field: combo.currentData()
            for field, combo in self.mapping_combos.items()
            if combo.currentData()
        }

    def _save_rule(self) -> None:
        name = self.name_input.text().strip()
        mapping = self._selected_mapping()
        if not name:
            show_error(self.error, t("请填写规则名称"))
            return
        if not mapping:
            show_error(self.error, t("至少映射日期、类型、金额和账户"))
            return
        try:
            if self.rule_id is not None:
                self.service.update_csv_rule(
                    self.rule_id,
                    name,
                    mapping,
                    dedup=self.dedup_check.isChecked(),
                )
            else:
                self.rule_id = self.service.add_csv_rule(
                    name, mapping, dedup=self.dedup_check.isChecked()
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self._reload_rules()
        index = self.rule_combo.findData(self.rule_id)
        if index >= 0:
            self.rule_combo.setCurrentIndex(index)
        self.hint.setText(t("规则已保存"))

    def _delete_rule(self) -> None:
        if self.rule_id is None:
            show_error(self.error, t("请选择一个已保存规则"))
            return
        if not ConfirmDialog.confirm(
            self,
            t("删除规则"),
            t("确定删除这条 CSV 导入规则？"),
            danger=True,
        ):
            return
        self.service.delete_csv_rule(self.rule_id)
        self.rule_id = None
        self.name_input.clear()
        self._reload_rules()
        self._set_rule(None)

    # ------------------------------------------------------------------- file
    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("选择 CSV 文件"), "", "CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            headers = self.service.import_headers(path)
        except (OSError, ValueError) as exc:
            show_error(self.error, str(exc))
            return
        self.path = Path(path)
        self.headers = headers
        self.file_label.setText(self.path.name)
        self.hint.setText(
            t("检测到 {count} 列：{headers}").format(
                count=len(headers), headers=", ".join(headers[:6])
            )
        )
        for combo in self.mapping_combos.values():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(t("（不使用）"), "")
            for header in headers:
                combo.addItem(header, header)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        auto = self._auto_mapping(headers)
        key = self._detect_preset(headers)
        index = self.preset_combo.findData(key)
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, index))
        self.preset_combo.blockSignals(False)
        if key:
            mapping = self._preset_mapping(key)
            for field, source in auto.items():
                mapping.setdefault(field, source)
            self._set_rule(mapping)
        else:
            for field, source in auto.items():
                index = self.mapping_combos[field].findData(source)
                if index >= 0:
                    self.mapping_combos[field].setCurrentIndex(index)

    def _preset_changed(self) -> None:
        key = self.preset_combo.currentData()
        if key and self.headers:
            self._set_rule(self._preset_mapping(key))

    def _preset_mapping(self, key: str) -> dict[str, str]:
        preset = IMPORT_PRESETS.get(key)
        if not preset:
            return {}
        mapping: dict[str, str] = {}
        for field, candidates in preset["fields"].items():
            for candidate in candidates:
                match = next(
                    (
                        header
                        for header in self.headers
                        if header.strip() == candidate
                    ),
                    None,
                )
                if match:
                    mapping[field] = match
                    break
            if field in mapping:
                continue
            for candidate in candidates:
                match = next(
                    (
                        header
                        for header in self.headers
                        if candidate in header
                    ),
                    None,
                )
                if match:
                    mapping[field] = match
                    break
        return mapping

    @staticmethod
    def _detect_preset(headers: list[str]) -> str | None:
        best_key = None
        best_score = 0
        for key, preset in IMPORT_PRESETS.items():
            score = 0
            for candidates in preset["fields"].values():
                if any(
                    header.strip() == candidate or candidate in header
                    for header in headers
                    for candidate in candidates
                ):
                    score += 1
            if score > best_score:
                best_key = key
                best_score = score
        return best_key if best_score >= 3 else None

    @staticmethod
    def _auto_mapping(headers: list[str]) -> dict[str, str]:
        from ...core.csv_io import _implicit_mapping

        return _implicit_mapping(headers)

    # ----------------------------------------------------------------- import
    def _import(self) -> None:
        if not self.path:
            show_error(self.error, t("请先选择 CSV 文件"))
            return
        mapping = self._selected_mapping()
        account_id = self.default_account_combo.currentData()
        missing = [
            field
            for field in ("date", "kind", "amount")
            if field not in mapping
        ]
        if account_id is None and "account" not in mapping:
            missing.append("account")
        if missing:
            show_error(self.error, t("请映射日期、类型、金额和账户"))
            return
        from ...core.models import CsvRule

        rule = CsvRule(
            id=self.rule_id or 0,
            name=self.name_input.text().strip() or "CSV",
            mapping=mapping,
            dedup=self.dedup_check.isChecked(),
        )
        try:
            result = self.service.import_csv(
                self.path,
                rule=rule,
                dedup=self.dedup_check.isChecked(),
                default_account_id=self.default_account_combo.currentData(),
            )
        except (OSError, ValueError) as exc:
            show_error(self.error, str(exc))
            return
        message = t("导入完成：成功 {imported} 笔，跳过 {skipped} 笔，重复 {duplicates} 笔。").format(
            imported=result.imported,
            skipped=result.skipped,
            duplicates=result.duplicates,
        )
        if result.errors:
            message += "\n\n" + "\n".join(result.errors[:6])
        ConfirmDialog.alert(self, t("导入 CSV"), message)
        if result.imported:
            self.accept()
