"""Application service: writes go through here and notify the UI."""

from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from PySide6.QtCore import QObject, Signal

from . import csv_io
from .dates import today_iso
from .models import (
    AccountValuation,
    Attachment,
    CsvRule,
    ForecastPoint,
    Holding,
    HoldingsSummary,
    ImportResult,
    Reconciliation,
    RecurringTransaction,
    SavingsGoal,
    Tag,
    TransactionBalance,
    TransactionFilter,
)
from .money import CURRENCIES, format_cents, format_compact, format_percentage
from .paths import attachment_path, attachments_dir
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

    def available_balance(
        self, account_id: int, exclude_transaction_id: int | None = None
    ) -> int:
        return self.repo.available_balance(account_id, exclude_transaction_id)

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

    def transaction_balances(
        self, transaction_ids: list[int]
    ) -> dict[int, TransactionBalance]:
        return self.repo.transaction_balances(transaction_ids)

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

    def valuations(
        self, account_id: int, *, limit: int | None = None
    ) -> list[AccountValuation]:
        return self.repo.valuations(account_id, limit=limit)

    def set_valuation(
        self, account_id: int, day: str, value: int, note: str = ""
    ) -> int:
        valuation_id = self.repo.set_valuation(account_id, day, value, note)
        self.changed.emit()
        return valuation_id

    def update_valuation(
        self, valuation_id: int, day: str, value: int, note: str = ""
    ) -> None:
        self.repo.update_valuation(valuation_id, day, value, note)
        self.changed.emit()

    def delete_valuation(self, valuation_id: int) -> None:
        self.repo.delete_valuation(valuation_id)
        self.changed.emit()

    # --------------------------------------------------------------- recurring
    def recurring_rules(
        self, *, active_only: bool = False
    ) -> list[RecurringTransaction]:
        return self.repo.recurring_rules(active_only=active_only)

    def due_recurring(self, day: str | None = None) -> list[RecurringTransaction]:
        return self.repo.due_recurring(day)

    def add_recurring(self, **fields) -> int:
        recurring_id = self.repo.add_recurring(**fields)
        self.changed.emit()
        return recurring_id

    def update_recurring(self, recurring_id: int, **fields) -> None:
        self.repo.update_recurring(recurring_id, **fields)
        self.changed.emit()

    def delete_recurring(self, recurring_id: int) -> None:
        self.repo.delete_recurring(recurring_id)
        self.changed.emit()

    def set_recurring_active(self, recurring_id: int, active: bool) -> None:
        self.repo.set_recurring_active(recurring_id, active)
        self.changed.emit()

    def post_recurring(self, recurring_id: int) -> int:
        transaction_id = self.repo.post_recurring(recurring_id)
        self.changed.emit()
        return transaction_id

    # ---------------------------------------------------------- reconciliation
    def reconciliations(
        self, account_id: int, *, limit: int = 50
    ) -> list[Reconciliation]:
        return self.repo.reconciliations(account_id, limit=limit)

    def reconcile_account(
        self,
        account_id: int,
        statement_balance: int,
        *,
        day: str | None = None,
        note: str = "",
    ) -> Reconciliation:
        reconciliation = self.repo.reconcile_account(
            account_id, statement_balance, day=day, note=note
        )
        self.changed.emit()
        return reconciliation

    def delete_reconciliation(self, reconciliation_id: int) -> None:
        self.repo.delete_reconciliation(reconciliation_id)
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
    def set_budget(
        self, month: str, category_id: int, amount: int, rollover: bool = False
    ) -> None:
        self.repo.upsert_budget(month, category_id, amount, rollover)
        self.changed.emit()

    def delete_budget(self, budget_id: int) -> None:
        self.repo.delete_budget(budget_id)
        self.changed.emit()

    # --------------------------------------------------------------- holdings
    def holdings(self, account_id: int | None = None) -> list[Holding]:
        return self.repo.holdings(account_id)

    def holdings_summary(self, account_id: int | None = None) -> HoldingsSummary:
        return self.repo.holdings_summary(account_id)

    def add_holding(self, account_id: int, name: str, **fields) -> int:
        holding_id = self.repo.add_holding(account_id, name, **fields)
        self.changed.emit()
        return holding_id

    def update_holding(self, holding_id: int, **fields) -> None:
        self.repo.update_holding(holding_id, **fields)
        self.changed.emit()

    def delete_holding(self, holding_id: int) -> None:
        self.repo.delete_holding(holding_id)
        self.changed.emit()

    def set_cash_balance(self, account_id: int, target: int) -> int:
        value = self.repo.set_cash_balance(account_id, target)
        self.changed.emit()
        return value

    def sync_holdings_value(self, account_id: int, day: str | None = None) -> int:
        summary = self.repo.holdings_summary(account_id)
        if not summary.count:
            raise ValueError("请先添加持仓")
        account = self.repo.get_account(account_id)
        # ``adjustment`` is added back by the balance query, so exclude it
        # from the snapshot to avoid counting it twice.
        cash = account.cash_balance - account.adjustment
        snapshot = cash + summary.market
        total = snapshot + account.adjustment
        self.repo.set_valuation(
            account_id,
            day or today_iso(),
            snapshot,
            "按持仓市值更新",
        )
        self.changed.emit()
        return total

    # ---------------------------------------------------------------- savings
    def savings_goals(self, *, include_archived: bool = False) -> list[SavingsGoal]:
        return self.repo.savings_goals(include_archived=include_archived)

    def add_savings_goal(self, name: str, target_amount: int, **fields) -> int:
        goal_id = self.repo.add_savings_goal(name, target_amount, **fields)
        self.changed.emit()
        return goal_id

    def update_savings_goal(self, goal_id: int, **fields) -> None:
        self.repo.update_savings_goal(goal_id, **fields)
        self.changed.emit()

    def add_goal_funds(self, goal_id: int, delta: int) -> None:
        self.repo.add_goal_funds(goal_id, delta)
        self.changed.emit()

    def delete_savings_goal(self, goal_id: int) -> None:
        self.repo.delete_savings_goal(goal_id)
        self.changed.emit()

    # --------------------------------------------------------------- forecast
    def cash_flow_forecast(
        self, months: int = 6, start_month: str | None = None
    ) -> list[ForecastPoint]:
        return self.repo.cash_flow_forecast(months, start_month)

    def liquid_balance(self) -> int:
        return self.repo.liquid_balance()

    # -------------------------------------------------------------- data tools
    def import_csv(
        self,
        path: str | Path,
        *,
        rule: CsvRule | None = None,
        dedup: bool = True,
    ) -> ImportResult:
        result = csv_io.import_csv(self.repo, path, rule=rule, dedup=dedup)
        if result.imported:
            self.changed.emit()
        return result

    def import_headers(self, path: str | Path) -> list[str]:
        return csv_io.read_headers(path)

    def csv_rules(self) -> list[CsvRule]:
        return self.repo.csv_rules()

    def add_csv_rule(
        self,
        name: str,
        mapping: dict[str, str],
        *,
        dedup: bool = True,
    ) -> int:
        rule_id = self.repo.add_csv_rule(name, mapping=mapping, dedup=dedup)
        self.changed.emit()
        return rule_id

    def update_csv_rule(
        self,
        rule_id: int,
        name: str,
        mapping: dict[str, str],
        *,
        dedup: bool = True,
    ) -> None:
        self.repo.update_csv_rule(rule_id, name=name, mapping=mapping, dedup=dedup)
        self.changed.emit()

    def delete_csv_rule(self, rule_id: int) -> None:
        self.repo.delete_csv_rule(rule_id)
        self.changed.emit()

    def tags(self) -> list[Tag]:
        return self.repo.tags()

    def set_transaction_metadata(
        self,
        transaction_id: int,
        *,
        splits: list[tuple[int, int, str]] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.repo.set_transaction_metadata(transaction_id, splits=splits, tags=tags)
        self.changed.emit()

    def attachments(self, transaction_id: int) -> list[Attachment]:
        return self.repo.attachments(transaction_id)

    def add_attachment(self, transaction_id: int, source: str | Path) -> int:
        source = Path(source)
        if not source.is_file():
            raise ValueError("附件文件不存在")
        attachments_dir()
        suffix = source.suffix[:20]
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        target = attachment_path(stored_name)
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise ValueError(f"无法复制附件：{exc}") from None
        try:
            attachment_id = self.repo.add_attachment(
                transaction_id,
                filename=source.name[:255],
                stored_name=stored_name,
                mime_type="",
                size=target.stat().st_size,
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self.changed.emit()
        return attachment_id

    def delete_attachment(self, attachment_id: int) -> None:
        attachment = self.repo.delete_attachment(attachment_id)
        attachment_path(attachment.stored_name).unlink(missing_ok=True)
        self.changed.emit()

    def attachment_file(self, attachment: Attachment) -> Path:
        return attachment_path(attachment.stored_name)

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
