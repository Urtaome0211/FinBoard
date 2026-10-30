"""Asset and liability accounts, with live balances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ...core.models import Account
from ..dialogs import HoldingsDialog, ReconcileDialog, ValuationDialog
from ..rows import AccountRow
from ..widgets import (
    Card,
    ConfirmDialog,
    EmptyState,
    Page,
    PageHeader,
    ThemedButton,
    clear_layout,
)
from .components import StatCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


class AccountsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("账户", "管理现金、银行卡、投资与负债")
        add_button = ThemedButton("新建账户", "primary", "plus")
        add_button.clicked.connect(lambda: self.window.open_account())
        header.add_action(add_button)
        self.header = header
        self.body.addWidget(header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.asset_card = StatCard("总资产", "wallet", tone="income")
        self.liability_card = StatCard("总负债", "credit-card", tone="expense")
        self.net_card = StatCard("净资产", "savings", tone="primary")
        self.ratio_card = StatCard("负债率", "shield", tone="warning")
        for card in (
            self.asset_card,
            self.liability_card,
            self.net_card,
            self.ratio_card,
        ):
            stats.addWidget(card, 1)
        self.body.addLayout(stats)

        self.asset_section = self._section("资产账户", "现金、储蓄卡与投资")
        self.liability_section = self._section("负债账户", "信用卡与贷款余额")
        self.archived_section = self._section("已归档账户", "不计入净资产")
        self.body.addWidget(self.asset_section[1])
        self.body.addWidget(self.liability_section[1])
        self.body.addWidget(self.archived_section[1])
        self.body.addStretch(1)

    def _section(self, title: str, hint: str):
        card = Card(padding=18, spacing=6)
        count = QLabel("0")
        count.setProperty("role", "muted")
        card.add_header(title, hint, count)
        layout = QVBoxLayout()
        layout.setSpacing(0)
        card.body.addLayout(layout)
        return layout, card, count

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        worth = self.service.repo.net_worth()
        money = self.service.format
        self.asset_card.set_value(
            money(worth.assets), hint=f"{worth.asset_accounts} 个资产账户", tone="text"
        )
        self.liability_card.set_value(
            money(worth.liabilities),
            hint=f"{worth.liability_accounts} 个负债账户",
            tone="expense" if worth.liabilities else "text",
        )
        self.net_card.set_value(
            money(worth.net),
            hint="资产 − 负债",
            tone="expense" if worth.net < 0 else "income",
        )
        self.ratio_card.set_value(
            f"{worth.liability_ratio:.1f}%",
            hint="负债 / (资产 + 负债)",
            tone="warning" if worth.liability_ratio else "text",
        )

        accounts = self.service.repo.accounts(include_archived=True)
        active = [account for account in accounts if not account.archived]
        archived = [account for account in accounts if account.archived]
        assets = sorted(
            (account for account in active if not account.is_liability),
            key=lambda account: account.balance,
            reverse=True,
        )
        liabilities = sorted(
            (account for account in active if account.is_liability),
            key=lambda account: account.balance,
        )
        self._fill(self.asset_section, assets, "还没有资产账户")
        self._fill(self.liability_section, liabilities, "没有负债，很好")
        self._fill(self.archived_section, archived, "没有已归档的账户")
        self.archived_section[1].setVisible(bool(archived))

    def _fill(self, section, accounts: list[Account], empty_hint: str) -> None:
        layout, card, count = section
        clear_layout(layout)
        count.setText(str(len(accounts)))
        if not accounts:
            layout.addWidget(
                EmptyState(
                    "wallet",
                    empty_hint,
                    "添加账户后，余额会随记账自动更新。",
                    "新建账户",
                    lambda: self.window.open_account(),
                )
            )
            return
        for account in accounts:
            row = AccountRow(account, self.service)
            row.edit_requested.connect(lambda item: self.window.open_account(item))
            row.archive_requested.connect(self._toggle_archive)
            row.delete_requested.connect(self._delete)
            row.valuation_requested.connect(self._open_valuation)
            row.holdings_requested.connect(self._open_holdings)
            row.reconcile_requested.connect(self._open_reconcile)
            layout.addWidget(row)

    def _open_valuation(self, account: Account) -> None:
        ValuationDialog(self.service, account, parent=self.window).exec()

    def _open_holdings(self, account: Account) -> None:
        HoldingsDialog(self.service, account, parent=self.window).exec()

    def _open_reconcile(self, account: Account) -> None:
        ReconcileDialog(self.service, account, parent=self.window).exec()

    def _toggle_archive(self, account: Account) -> None:
        if account.archived:
            self.service.set_account_archived(account.id, False)
            self.window.notify(f"已恢复账户「{account.name}」")
            return
        if not ConfirmDialog.confirm(
            self,
            "归档这个账户？",
            f"「{account.name}」将不再计入净资产和账户列表，历史记录会保留，之后可以恢复。",
            ok_text="归档",
            icon_name="archive",
        ):
            return
        self.service.set_account_archived(account.id, True)
        self.window.notify(f"已归档账户「{account.name}」")

    def _delete(self, account: Account) -> None:
        if not ConfirmDialog.confirm(
            self,
            "删除这个账户？",
            f"「{account.name}」删除后无法恢复。已有交易记录的账户不能删除，只能归档。",
            ok_text="删除",
            danger=True,
            icon_name="trash",
        ):
            return
        try:
            self.service.delete_account(account.id)
        except ValueError as exc:
            ConfirmDialog.alert(self, "无法删除账户", str(exc), icon_name="alert")
            return
        self.window.notify(f"已删除账户「{account.name}」")
