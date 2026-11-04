"""Fixed assets: property, vehicles and other long-term holdings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.models import FixedAsset
from ...core.service import FinanceService
from ...i18n import fixed_asset_type_display, t
from ..dialogs.fixed_asset_dialog import FixedAssetDialog
from ..icons import icon
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
    progress_bar,
)
from .components import StatCard


class FixedAssetRow(QFrame):
    edit_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, asset: FixedAsset, service: FinanceService, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ListRow")
        self.setFixedHeight(82)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.asset = asset
        palette = colors()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(12)

        layout.addWidget(
            icon_label(
                asset.icon_name,
                palette.primary,
                size=19,
                background=palette.primary_soft,
                box=40,
            )
        )

        text = QVBoxLayout()
        text.setSpacing(4)
        title = QHBoxLayout()
        title.setSpacing(7)
        name = ElidedLabel(asset.name, size=13, weight=600)
        name.setProperty("i18nSkip", True)
        name.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        name.setMinimumWidth(80)
        name.setStyleSheet("background: transparent;")
        title.addWidget(name)
        title.addWidget(
            Badge(fixed_asset_type_display(asset.type_label), "primary")
        )
        title.addStretch(1)
        text.addLayout(title)

        note = ElidedLabel(
            f"{t('估值日')} {asset.valuation_date}"
            + (f" · {asset.note}" if asset.note else ""),
            role="muted",
            size=12,
        )
        note.setProperty("i18nSkip", True)
        text.addWidget(note)
        layout.addLayout(text, 1)

        money_col = QVBoxLayout()
        money_col.setSpacing(4)
        value = ValueLabel(service.format_money(asset.current_value, asset.currency), size=14)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        money_col.addWidget(value)
        gain = ValueLabel(
            t("购买价 {price}", price=service.format_money(asset.purchase_price, asset.currency)),
            tone="faint",
            size=11,
            weight=500,
        )
        gain.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        money_col.addWidget(gain)
        layout.addLayout(money_col)

        gain_col = QVBoxLayout()
        gain_col.setSpacing(4)
        gain_value = ValueLabel(
            service.format_money(asset.gain, asset.currency, plus=asset.gain > 0),
            size=13,
            weight=600,
        )
        gain_value.set_tone("income" if asset.gain >= 0 else "expense")
        gain_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        gain_col.addWidget(gain_value)
        rate = QLabel(t("{rate}%", rate=f"{asset.gain_rate:.1f}"))
        rate.setProperty("role", "faint")
        rate.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        gain_col.addWidget(rate)
        layout.addLayout(gain_col)

        edit = IconButton("edit", t("编辑资产"), size=16)
        edit.setFixedSize(30, 30)
        edit.clicked.connect(lambda _checked=False: self.edit_requested.emit(self.asset))
        layout.addWidget(edit)
        delete = IconButton("trash", t("删除资产"), size=16)
        delete.setFixedSize(30, 30)
        delete.clicked.connect(
            lambda _checked=False: self.delete_requested.emit(self.asset)
        )
        layout.addWidget(delete)


class FixedAssetsPage(Page):
    def __init__(self, service: FinanceService, window) -> None:
        super().__init__()
        self.service = service
        self.window = window

        self.header = PageHeader(
            t("固定资产"),
            t("房产、车辆等长期资产；不计入可用现金和现金流预测"),
        )
        add = ThemedButton(t("新增资产"), "primary", "plus")
        add.clicked.connect(lambda _checked=False: self._add())
        self.header.add_action(add)
        self.body.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(16)
        self.value_card = StatCard(t("固定资产总值"), "home", tone="primary")
        self.cost_card = StatCard(t("购买成本"), "wallet", tone="muted")
        self.gain_card = StatCard(t("累计增值"), "trending-up", tone="income")
        self.ratio_card = StatCard(t("占总资产"), "chart", tone="accent")
        for card in (self.value_card, self.cost_card, self.gain_card, self.ratio_card):
            stats.addWidget(card, 1)
        self.body.addLayout(stats)

        self.card = Card(padding=18, spacing=6)
        self.count = QLabel("0")
        self.count.setProperty("role", "muted")
        self.card.add_header(t("资产清单"), t("按当前估值从高到低"), self.count)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.card.body.addLayout(self.list_layout)
        self.body.addWidget(self.card)
        self.body.addStretch(1)

    def _add(self) -> None:
        dialog = FixedAssetDialog(self.service, parent=self.window)
        if dialog.exec():
            self.window.notify(t("固定资产已添加"))
            self.refresh()

    def _edit(self, asset: FixedAsset) -> None:
        dialog = FixedAssetDialog(self.service, asset, parent=self.window)
        if dialog.exec():
            self.window.notify(t("固定资产已更新"))
            self.refresh()

    def _delete(self, asset: FixedAsset) -> None:
        if not ConfirmDialog.confirm(
            self.window,
            t("删除固定资产"),
            t("确定删除「{name}」？此操作不会生成收支记录。", name=asset.name),
            danger=True,
            icon_name="trash",
        ):
            return
        self.service.delete_fixed_asset(asset.id)
        self.window.notify(t("固定资产已删除"))

    def _fill(self, assets: list[FixedAsset]) -> None:
        clear_layout(self.list_layout)
        self.count.setText(str(len(assets)))
        if not assets:
            self.list_layout.addWidget(
                EmptyState(
                    "home",
                    t("还没有固定资产"),
                    t("记录房产、车辆等长期资产，让总资产更完整。"),
                    t("新增资产"),
                    self._add,
                )
            )
            return
        for asset in assets:
            row = FixedAssetRow(asset, self.service)
            row.edit_requested.connect(self._edit)
            row.delete_requested.connect(self._delete)
            self.list_layout.addWidget(row)

    def refresh(self) -> None:
        assets = self.service.repo.fixed_assets()
        self._fill(assets)
        worth = self.service.repo.net_worth()
        money = self.service.format
        fixed = worth.fixed_assets
        purchase = 0
        for asset in assets:
            try:
                purchase += self.service.to_base(
                    asset.purchase_price, asset.currency, asset.valuation_date
                )
            except ValueError:
                purchase += asset.purchase_price
        gain = fixed - purchase
        self.value_card.set_value(
            money(fixed), hint=t("{count} 项资产", count=len(assets))
        )
        self.cost_card.set_value(money(purchase), hint=t("手动填写的购买价"))
        self.gain_card.set_value(
            money(gain, plus=gain > 0),
            hint=t("当前估值 − 购买价"),
            tone="income" if gain >= 0 else "expense",
        )
        ratio = (fixed / worth.assets * 100) if worth.assets else 0.0
        self.ratio_card.set_value(f"{ratio:.1f}%", hint=t("固定资产 / 总资产"))

    # keep the base class' scroll page and expose a stable hook
    def set_subtitle(self, text: str) -> None:
        self.header.set_subtitle(text)
