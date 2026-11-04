"""Create or edit a fixed asset (home, vehicle, other long-term property)."""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from ...core.models import FIXED_ASSET_TYPE_META, FIXED_ASSET_TYPES, FixedAsset
from ...core.money import CURRENCIES, parse_signed_amount
from ...core.service import FinanceService
from ...i18n import currency_display, fixed_asset_type_display, t
from ..icons import icon
from ..theme import colors
from .common import (
    dialog_footer,
    dialog_header,
    error_label,
    form_label,
    root_layout,
    show_error,
)


class FixedAssetDialog(QDialog):
    def __init__(
        self,
        service: FinanceService,
        asset: FixedAsset | None = None,
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.asset = asset
        self.setWindowTitle(t("编辑固定资产" if asset else "新建固定资产"))
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = root_layout(self)
        header, _ = dialog_header(
            t("编辑固定资产" if asset else "新建固定资产"),
            t("长期持有、不用于日常支付；只影响总资产与净资产"),
            "home",
        )
        layout.addLayout(header)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(t("例如：自住房、家用车"))
        self.name_input.setMaxLength(60)
        form.addRow(form_label(t("资产名称")), self.name_input)

        self.type_combo = QComboBox()
        palette = colors()
        for type_name in FIXED_ASSET_TYPES:
            meta = FIXED_ASSET_TYPE_META[type_name]
            self.type_combo.addItem(
                icon(meta["icon"], palette.muted, 17),
                fixed_asset_type_display(meta["label"]),
                type_name,
            )
        form.addRow(form_label(t("资产类型")), self.type_combo)

        self.purchase_input = QLineEdit()
        self.purchase_input.setPlaceholderText(t("购买时的价格，0 表示未填写"))
        self.purchase_input.setMaxLength(20)
        form.addRow(form_label(t("购买价")), self.purchase_input)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText(t("当前估值，例如：1200000"))
        self.value_input.setMaxLength(20)
        form.addRow(form_label(t("当前估值")), self.value_input)

        self.currency_combo = QComboBox()
        for code, meta in CURRENCIES.items():
            self.currency_combo.addItem(
                currency_display(code, meta["symbol"], meta["name"]), code
            )
        form.addRow(form_label(t("币种")), self.currency_combo)

        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow(form_label(t("估值日期")), self.date_edit)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(t("可选备注，例如：小区、车牌"))
        self.note_input.setMaxLength(200)
        form.addRow(form_label(t("备注")), self.note_input)
        layout.addLayout(form)

        self.preview = QLabel()
        self.preview.setProperty("role", "faint")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.error = error_label()
        layout.addWidget(self.error)
        footer = dialog_footer(
            self, self.error, save_text=t("保存资产") if asset else t("创建资产")
        )
        self.save_button = footer.itemAt(footer.count() - 1).widget()
        self.save_button.clicked.connect(self._save)
        layout.addLayout(footer)

        if asset:
            self.name_input.setText(asset.name)
            index = self.type_combo.findData(asset.type)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.purchase_input.setText(self._amount_text(asset.purchase_price))
            self.value_input.setText(self._amount_text(asset.current_value))
            index = self.currency_combo.findData(asset.currency)
            if index >= 0:
                self.currency_combo.setCurrentIndex(index)
            self.date_edit.setDate(QDate.fromString(asset.valuation_date, "yyyy-MM-dd"))
            self.note_input.setText(asset.note)

        self.purchase_input.textChanged.connect(self._update_preview)
        self.value_input.textChanged.connect(self._update_preview)
        self.currency_combo.currentIndexChanged.connect(self._update_preview)
        self._update_preview()
        self.name_input.setFocus()

    @staticmethod
    def _amount_text(value: int) -> str:
        return f"{value // 100}.{value % 100:02d}"

    def _update_preview(self, *_args) -> None:
        try:
            purchase = parse_signed_amount(self.purchase_input.text() or "0")
            current = parse_signed_amount(self.value_input.text() or "0")
        except ValueError:
            self.preview.setText(t("输入购买价与当前估值后显示增值/贬值"))
            return
        if purchase < 0 or current < 0:
            self.preview.setText(t("金额不能为负数"))
            return
        gain = current - purchase
        rate = (gain / purchase * 100) if purchase else 0.0
        symbol = CURRENCIES.get(
            self.currency_combo.currentData() or "CNY", CURRENCIES["CNY"]
        )["symbol"]
        text = t(
            "增值 {gain}（{rate}%）",
            gain=f"{symbol}{abs(gain) // 100}.{abs(gain) % 100:02d}",
            rate=f"{rate:.1f}",
        )
        if gain < 0:
            text = t(
                "贬值 {loss}（{rate}%）",
                loss=f"{symbol}{abs(gain) // 100}.{abs(gain) % 100:02d}",
                rate=f"{abs(rate):.1f}",
            )
        self.preview.setText(text)

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            show_error(self.error, t("请输入资产名称"))
            self.name_input.setFocus()
            return
        type_name = self.type_combo.currentData()
        if type_name not in FIXED_ASSET_TYPE_META:
            show_error(self.error, t("请选择资产类型"))
            return
        try:
            purchase = parse_signed_amount(self.purchase_input.text() or "0")
            current = parse_signed_amount(self.value_input.text() or "0")
        except ValueError as exc:
            show_error(self.error, str(exc))
            self.value_input.setFocus()
            return
        if purchase < 0 or current < 0:
            show_error(self.error, t("金额不能为负数"))
            return
        try:
            if self.asset:
                self.service.update_fixed_asset(
                    self.asset.id,
                    name=name,
                    type_=type_name,
                    purchase_price=purchase,
                    current_value=current,
                    valuation_date=self.date_edit.date().toString("yyyy-MM-dd"),
                    currency=self.currency_combo.currentData() or "CNY",
                    note=self.note_input.text().strip(),
                )
            else:
                self.service.add_fixed_asset(
                    name,
                    type_name,
                    purchase,
                    current,
                    self.date_edit.date().toString("yyyy-MM-dd"),
                    currency=self.currency_combo.currentData() or "CNY",
                    note=self.note_input.text().strip(),
                )
        except ValueError as exc:
            show_error(self.error, str(exc))
            return
        self.accept()
