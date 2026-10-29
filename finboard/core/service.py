"""Application service: writes go through here and notify the UI."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import csv_io
from .models import ImportResult, TransactionFilter
from .money import CURRENCIES, format_cents, format_compact, format_percentage
from .rates import RateSnapshot, RateStore
from .repository import Repository


class FinanceService(QObject):
    """Thin command layer around :class:`Repository`.

    Every mutating operation emits ``changed`` exactly once so widgets can
    refresh without any manual bookkeeping.
    """

    changed = Signal()

    def __init__(
        self,
        repository: Repository,
        currency: str = "CNY",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.repo = repository
        self.rate_store: RateStore = repository.rates
        self._currency = currency if currency in CURRENCIES else "CNY"
        repository.set_base_currency(self._currency)

    # -------------------------------------------------------------- formatting
    @property
    def currency(self) -> str:
        return self._currency

    @property
    def symbol(self) -> str:
        return CURRENCIES[self._currency]["symbol"]

    def set_currency(self, code: str) -> None:
        if code not in CURRENCIES:
            raise ValueError("不支持的币种")
        if code == self._currency:
            return
        if code != "CNY" and not self.rate_store.has_rates():
            raise ValueError("请先在“汇率”区域更新汇率，再切换基准币种")
        self._currency = code
        self.repo.set_base_currency(code)
        self.changed.emit()

    def format(self, cents: int, *, plus: bool = False) -> str:
        return format_cents(cents, self.symbol, plus=plus)

    def format_money(self, cents: int, currency: str, *, plus: bool = False) -> str:
        symbol = CURRENCIES.get(currency, CURRENCIES["CNY"])["symbol"]
        return format_cents(cents, symbol, plus=plus)

    def format_compact(self, cents: int) -> str:
        return format_compact(cents, self.symbol)

    def percent(self, part: int, total: int, digits: int = 1) -> str:
        return format_percentage(part, total, digits)

    def to_base(self, cents: int, currency: str, day: str | None = None) -> int:
        return self.repo._to_base(cents, currency, day)

    def refresh(self) -> None:
        self.changed.emit()

    # ------------------------------------------------------------------ rates
    def refresh_rates(self, *, force: bool = False) -> RateSnapshot | None:
        snapshot = self.rate_store.refresh(force=force)
        if snapshot is not None:
            self.changed.emit()
        return snapshot

    def rate_summary(self) -> str:
        latest = self.rate_store.latest_date()
        if not latest:
            return "尚未更新汇率"
        error = self.rate_store.last_error()
        if error:
            return f"使用缓存汇率 {latest}（更新失败）"
        return f"汇率日期 {latest}"

    # ------------------------------------------------------------ transactions
    def add_transaction(self, **fields) -> int:
        transaction_id = self.repo.add_transaction(**fields)
        self.changed.emit()
        return transaction_id

    def update_transaction(self, transaction_id: int, **fields) -> None:
        self.repo.update_transaction(transaction_id, **fields)
        self.changed.emit()

    def delete_transaction(self, transaction_id: int) -> None:
        self.repo.delete_transaction(transaction_id)
        self.changed.emit()

    # ---------------------------------------------------------------- accounts
    def add_account(
        self,
        name: str,
        type_: str,
        opening_balance: int = 0,
        note: str = "",
        currency: str = "CNY",
    ) -> int:
        if currency != "CNY" and not self.rate_store.has_rates():
            raise ValueError("请先在设置中更新汇率，再创建外币账户")
        account_id = self.repo.add_account(
            name, type_, opening_balance, note, currency=currency
        )
        self.changed.emit()
        return account_id

    def update_account(self, account_id: int, **fields) -> None:
        currency = fields.get("currency")
        if currency and currency != "CNY" and not self.rate_store.has_rates():
            raise ValueError("请先在设置中更新汇率，再使用外币账户")
        self.repo.update_account(account_id, **fields)
        self.changed.emit()

    def delete_account(self, account_id: int) -> None:
        self.repo.delete_account(account_id)
        self.changed.emit()

    def set_account_archived(self, account_id: int, archived: bool) -> None:
        self.repo.set_account_archived(account_id, archived)
        self.changed.emit()

    # -------------------------------------------------------------- categories
    def add_category(self, name: str, kind: str, color: str = "#95A0B5") -> int:
        category_id = self.repo.add_category(name, kind, color)
        self.changed.emit()
        return category_id

    def update_category(self, category_id: int, **fields) -> None:
        self.repo.update_category(category_id, **fields)
        self.changed.emit()

    def delete_category(self, category_id: int) -> str:
        fallback = self.repo.delete_category(category_id)
        self.changed.emit()
        return fallback

    # ----------------------------------------------------------------- budgets
    def set_budget(self, month: str, category_id: int, amount: int) -> None:
        self.repo.upsert_budget(month, category_id, amount)
        self.changed.emit()

    def delete_budget(self, budget_id: int) -> None:
        self.repo.delete_budget(budget_id)
        self.changed.emit()

    # -------------------------------------------------------------- data tools
    def import_csv(self, path: str | Path) -> ImportResult:
        result = csv_io.import_csv(self.repo, path)
        if result.imported:
            self.changed.emit()
        return result

    def export_csv(
        self, path: str | Path, filters: TransactionFilter | None = None
    ) -> int:
        return csv_io.export_csv(self.repo, path, filters)

    def seed_demo(self) -> None:
        from .demo import seed_demo

        seed_demo(self.repo)
        self.changed.emit()

    def clear_all(self) -> None:
        self.repo.clear_all(seed_defaults=True)
        self.changed.emit()
