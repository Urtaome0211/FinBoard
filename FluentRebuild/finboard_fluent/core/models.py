"""Plain data models shared by the repository, service and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .money import demand_deposit_interest, term_deposit_interest

TxnKind = Literal["expense", "income", "transfer"]
CategoryKind = Literal["expense", "income"]

KIND_LABELS: dict[str, str] = {
    "expense": "支出",
    "income": "收入",
    "transfer": "转账",
}

ACCOUNT_TYPE_META: dict[str, dict[str, str]] = {
    "cash": {"label": "现金", "icon": "cash", "group": "asset"},
    "debit": {"label": "储蓄卡", "icon": "bank", "group": "asset"},
    "investment": {"label": "投资理财", "icon": "investment", "group": "asset"},
    "credit": {"label": "信用卡", "icon": "credit-card", "group": "liability"},
    "loan": {"label": "贷款", "icon": "loan", "group": "liability"},
}
ACCOUNT_TYPES = tuple(ACCOUNT_TYPE_META)

FIXED_ASSET_TYPE_META: dict[str, dict[str, str]] = {
    "property": {"label": "房产", "icon": "home"},
    "vehicle": {"label": "车辆", "icon": "car"},
    "other": {"label": "其他", "icon": "tag"},
}
FIXED_ASSET_TYPES = tuple(FIXED_ASSET_TYPE_META)

DEFAULT_COLORS = (
    "#F2994A",
    "#5B8DEF",
    "#27AE60",
    "#7C6CF2",
    "#F2C94C",
    "#EB5757",
    "#2D9CDB",
    "#56CCF2",
    "#F178B6",
    "#95A0B5",
)

DEFAULT_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("餐饮", "expense", "#F2994A"),
    ("购物", "expense", "#5B8DEF"),
    ("交通", "expense", "#27AE60"),
    ("居住", "expense", "#7C6CF2"),
    ("娱乐", "expense", "#F2C94C"),
    ("医疗", "expense", "#EB5757"),
    ("教育", "expense", "#2D9CDB"),
    ("通讯", "expense", "#56CCF2"),
    ("旅行", "expense", "#F178B6"),
    ("其他", "expense", "#95A0B5"),
    ("工资", "income", "#27AE60"),
    ("奖金", "income", "#F2994A"),
    ("理财", "income", "#5B8DEF"),
    ("兼职", "income", "#7C6CF2"),
    ("其他", "income", "#95A0B5"),
)

#: Categories of this kind are re-created automatically when reassigning rows.
FALLBACK_CATEGORY = "其他"


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    type: str
    opening_balance: int
    note: str = ""
    archived: bool = False
    balance: int = 0
    currency: str = "CNY"
    last_valuation: int | None = None
    last_valuation_date: str = ""
    valuation_count: int = 0
    adjustment: int = 0
    holdings_value: int = 0
    is_system: bool = False

    @property
    def cash_balance(self) -> int:
        """Cash part of an investment account (total value minus holdings)."""
        if self.type == "investment":
            return self.balance - self.holdings_value
        return self.balance

    @property
    def type_label(self) -> str:
        return ACCOUNT_TYPE_META[self.type]["label"]

    @property
    def icon_name(self) -> str:
        return ACCOUNT_TYPE_META[self.type]["icon"]

    @property
    def group(self) -> str:
        return ACCOUNT_TYPE_META[self.type]["group"]

    @property
    def is_liability(self) -> bool:
        return self.group == "liability"


@dataclass(frozen=True)
class AccountValuation:
    id: int
    account_id: int
    date: str
    value: int
    note: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class Debt:
    """A loan or credit-card profile attached to a liability account."""

    id: int
    account_id: int
    kind: str
    principal: int = 0
    annual_rate_bp: int = 0
    term_months: int = 0
    start_date: str | None = None
    payment_method: str = "equal_payment"
    billing_day: int | None = None
    due_day: int | None = None
    credit_limit: int = 0
    min_payment_bp: int = 1000
    note: str = ""
    created_at: str = ""
    account_name: str = ""
    account_balance: int = 0
    currency: str = "CNY"

    @property
    def is_loan(self) -> bool:
        return self.kind == "loan"

    @property
    def is_credit(self) -> bool:
        return self.kind == "credit"

    @property
    def outstanding(self) -> int:
        return abs(int(self.account_balance))

    @property
    def rate_text(self) -> str:
        return f"{self.annual_rate_bp / 100:.2f}%"

    @property
    def min_payment(self) -> int:
        if self.outstanding <= 0:
            return 0
        return min(
            self.outstanding,
            (self.outstanding * self.min_payment_bp + 9999) // 10000,
        )

    @property
    def utilization(self) -> float:
        if not self.is_credit or self.credit_limit <= 0:
            return 0.0
        return round(self.outstanding / self.credit_limit * 100, 1)

    @property
    def paid_progress(self) -> float:
        if self.principal <= 0:
            return 0.0
        return round(min(100.0, (1 - self.outstanding / self.principal) * 100), 1)


@dataclass(frozen=True)
class DebtPayment:
    """A repayment recorded against a loan or credit-card liability."""

    id: int
    account_id: int
    paid_on: str
    amount: int
    principal: int = 0
    interest: int = 0
    transfer_id: int | None = None
    interest_transaction_id: int | None = None
    note: str = ""
    created_at: str = ""
    account_name: str = ""
    currency: str = "CNY"

    @property
    def is_interest_only(self) -> bool:
        return self.principal <= 0 and self.interest > 0


@dataclass(frozen=True)
class TransactionTemplate:
    """A reusable transaction draft for fast data entry."""

    id: int
    name: str
    kind: str
    amount: int = 0
    currency: str = "CNY"
    category_id: int | None = None
    category_name: str = ""
    account_id: int | None = None
    account_name: str = ""
    to_account_id: int | None = None
    to_account_name: str = ""
    payee: str = ""
    note: str = ""
    created_at: str = ""

    @property
    def title(self) -> str:
        if self.payee:
            return self.payee
        if self.category_name:
            return self.category_name
        return self.name


@dataclass(frozen=True)
class FixedAssetValuation:
    id: int
    asset_id: int
    value: int
    valued_on: str
    note: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class Holding:
    id: int
    account_id: int
    name: str
    symbol: str = ""
    quantity_units: int = 0
    cost_price: int = 0
    price: int = 0
    note: str = ""
    created_at: str = ""
    currency: str = "CNY"
    account_name: str = ""
    realized_profit: int = 0
    dividends: int = 0
    asset_class: str = ""
    region: str = ""

    @property
    def cost_value(self) -> int:
        return (self.quantity_units * self.cost_price + 500_000) // 1_000_000

    @property
    def market_value(self) -> int:
        return (self.quantity_units * self.price + 500_000) // 1_000_000

    @property
    def profit(self) -> int:
        return self.market_value - self.cost_value

    @property
    def total_profit(self) -> int:
        return self.profit + self.realized_profit + self.dividends

    @property
    def return_rate(self) -> float:
        if self.cost_value <= 0:
            return 0.0
        return round(self.profit / self.cost_value * 100, 2)

    @property
    def total_return_rate(self) -> float:
        if self.cost_value <= 0:
            return 0.0
        return round(self.total_profit / self.cost_value * 100, 2)


@dataclass(frozen=True)
class InvestmentTrade:
    """A buy, sell or dividend event for an investment account."""

    id: int
    account_id: int
    symbol: str
    name: str
    kind: str
    trade_date: str
    quantity_units: int = 0
    price: int = 0
    fee: int = 0
    amount: int = 0
    currency: str = "CNY"
    note: str = ""
    created_at: str = ""
    account_name: str = ""

    @property
    def gross_value(self) -> int:
        return (self.quantity_units * self.price + 500_000) // 1_000_000

    @property
    def net_value(self) -> int:
        if self.kind == "dividend":
            return self.amount
        if self.kind == "buy":
            return self.gross_value + self.fee
        return self.gross_value - self.fee

    @property
    def label(self) -> str:
        return {"buy": "买入", "sell": "卖出", "dividend": "分红"}.get(
            self.kind, self.kind
        )


@dataclass(frozen=True)
class InvestmentLot:
    """A FIFO lot created by a buy trade."""

    id: int
    trade_id: int
    account_id: int
    symbol: str
    name: str
    acquired_date: str
    quantity_units: int
    remaining_units: int
    unit_cost: int
    currency: str = "CNY"
    created_at: str = ""

    @property
    def cost_value(self) -> int:
        return (self.remaining_units * self.unit_cost + 500_000) // 1_000_000

    @property
    def remaining_ratio(self) -> float:
        if self.quantity_units <= 0:
            return 0.0
        return round(self.remaining_units / self.quantity_units * 100, 1)


@dataclass(frozen=True)
class InvestmentDisposal:
    """One FIFO allocation produced by a sell trade."""

    id: int
    sell_trade_id: int
    lot_id: int
    quantity_units: int
    cost: int
    proceeds: int
    realized: int
    created_at: str = ""


@dataclass(frozen=True)
class HoldingsSummary:
    cost: int = 0
    market: int = 0
    count: int = 0
    realized: int = 0
    dividends: int = 0

    @property
    def profit(self) -> int:
        return self.market - self.cost

    @property
    def total_profit(self) -> int:
        return self.profit + self.realized + self.dividends

    @property
    def return_rate(self) -> float:
        if self.cost <= 0:
            return 0.0
        return round(self.profit / self.cost * 100, 2)

    @property
    def total_return_rate(self) -> float:
        if self.cost <= 0:
            return 0.0
        return round(self.total_profit / self.cost * 100, 2)


@dataclass(frozen=True)
class BulkResult:
    updated: int = 0
    skipped: int = 0
    message: str = ""


@dataclass(frozen=True)
class SavingsGoal:
    id: int
    name: str
    target_amount: int
    saved_amount: int = 0
    target_date: str | None = None
    note: str = ""
    archived: bool = False
    created_at: str = ""

    @property
    def remaining(self) -> int:
        return max(0, self.target_amount - self.saved_amount)

    @property
    def progress(self) -> float:
        if self.target_amount <= 0:
            return 0.0
        return round(min(100.0, self.saved_amount / self.target_amount * 100), 1)

    @property
    def completed(self) -> bool:
        return self.saved_amount >= self.target_amount


@dataclass(frozen=True)
class TermDeposit:
    """A fixed-term deposit funded from one account and paid back to another."""

    id: int
    name: str
    principal: int
    currency: str
    annual_rate_bp: int
    term_months: int
    start_date: str
    maturity_date: str
    early_rate_bp: int
    source_account_id: int
    deposit_account_id: int
    destination_account_id: int
    status: str = "active"
    close_reason: str = ""
    interest_paid: int = 0
    closed_at: str = ""
    note: str = ""
    created_at: str = ""
    source_account_name: str = ""
    deposit_account_name: str = ""
    destination_account_name: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_matured(self) -> bool:
        if not self.is_active:
            return False
        try:
            return date.today() >= date.fromisoformat(self.maturity_date)
        except ValueError:
            return False

    @property
    def maturity_interest(self) -> int:
        return term_deposit_interest(
            self.principal, self.annual_rate_bp, self.term_months
        )

    @property
    def annual_rate_text(self) -> str:
        return f"{self.annual_rate_bp / 100:.2f}%"

    @property
    def early_rate_text(self) -> str:
        return f"{self.early_rate_bp / 100:.2f}%"

    @property
    def elapsed_days(self) -> int:
        try:
            return max(
                0,
                (date.today() - date.fromisoformat(self.start_date)).days,
            )
        except ValueError:
            return 0

    @property
    def total_days(self) -> int:
        try:
            return max(
                1,
                (date.fromisoformat(self.maturity_date) - date.fromisoformat(self.start_date)).days,
            )
        except ValueError:
            return 1

    @property
    def progress(self) -> float:
        if not self.is_active:
            return 100.0
        return round(min(100.0, self.elapsed_days / self.total_days * 100), 1)

    def early_interest(self, on: str | None = None) -> int:
        try:
            start = date.fromisoformat(self.start_date)
            end = date.fromisoformat(on) if on else date.today()
        except ValueError:
            return 0
        return demand_deposit_interest(
            self.principal, self.early_rate_bp, (end - start).days
        )


@dataclass(frozen=True)
class ForecastPoint:
    month: str
    income: int
    expense: int
    net: int
    ending_cash: int


@dataclass(frozen=True)
class RecurringTransaction:
    id: int
    name: str
    kind: str
    amount: int
    account_id: int
    account_name: str = ""
    category_id: int | None = None
    category_name: str = ""
    to_account_id: int | None = None
    to_account_name: str = ""
    payee: str = ""
    note: str = ""
    fee_waived: bool = False
    frequency: str = "monthly"
    interval_count: int = 1
    start_date: str = ""
    end_date: str | None = None
    next_date: str = ""
    active: bool = True
    currency: str = "CNY"
    created_at: str = ""

    @property
    def title(self) -> str:
        return self.name or self.payee or self.category_name


@dataclass(frozen=True)
class PlannedTransaction:
    id: int
    date: str
    kind: str
    amount: int
    currency: str = "CNY"
    account_id: int = 0
    account_name: str = ""
    category_id: int | None = None
    category_name: str = ""
    to_account_id: int | None = None
    to_account_name: str = ""
    payee: str = ""
    note: str = ""
    status: str = "planned"
    transaction_id: int | None = None
    created_at: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == "planned"

    @property
    def signed_amount(self) -> int:
        if self.kind == "income":
            return self.amount
        if self.kind == "expense":
            return -self.amount
        return 0

    @property
    def title(self) -> str:
        return self.payee or self.category_name or self.note or KIND_LABELS.get(self.kind, "")


@dataclass(frozen=True)
class Receivable:
    id: int
    direction: str
    counterparty: str
    amount: int
    currency: str = "CNY"
    date: str = ""
    due_date: str | None = None
    account_id: int | None = None
    account_name: str = ""
    note: str = ""
    status: str = "open"
    settled_at: str | None = None
    created_at: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def is_receivable(self) -> bool:
        return self.direction == "receivable"

    @property
    def signed_amount(self) -> int:
        return self.amount if self.is_receivable else -self.amount

    @property
    def days_left(self) -> int | None:
        if not self.due_date:
            return None
        try:
            return (date.fromisoformat(self.due_date) - date.today()).days
        except ValueError:
            return None


@dataclass(frozen=True)
class Reconciliation:
    id: int
    account_id: int
    date: str
    statement_balance: int
    ledger_balance: int
    difference: int
    note: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    kind: str
    color: str

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass(frozen=True)
class Tag:
    id: int
    name: str
    color: str = "#5B8DEF"


@dataclass(frozen=True)
class TransactionSplit:
    id: int
    transaction_id: int
    category_id: int
    category_name: str
    category_color: str
    amount: int
    note: str = ""
    position: int = 0


@dataclass(frozen=True)
class Attachment:
    id: int
    transaction_id: int
    filename: str
    stored_name: str
    mime_type: str = ""
    size: int = 0
    created_at: str = ""


@dataclass(frozen=True)
class CsvRule:
    id: int
    name: str
    mapping: dict[str, str] = field(default_factory=dict)
    default_kind: str = "expense"
    default_account_id: int | None = None
    default_category_id: int | None = None
    dedup: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Transaction:
    id: int
    date: str
    kind: str
    amount: int
    account_id: int
    account_name: str
    category_id: int | None = None
    category_name: str = ""
    category_color: str = ""
    to_account_id: int | None = None
    to_account_name: str = ""
    payee: str = ""
    note: str = ""
    created_at: str = ""
    currency: str = "CNY"
    account_amount: int = 0
    to_amount: int = 0
    fee: int = 0
    fee_waived: bool = False
    fee_included: bool = False
    recurring_id: int | None = None
    refund_of_id: int | None = None
    account_currency: str = "CNY"
    to_account_currency: str = "CNY"
    import_hash: str = ""
    splits: tuple[TransactionSplit, ...] = ()
    tags: tuple[Tag, ...] = ()
    attachments: tuple[Attachment, ...] = ()

    @property
    def signed_amount(self) -> int:
        if self.kind == "income":
            return self.amount
        if self.kind == "expense":
            return -self.amount
        return self.amount

    @property
    def title(self) -> str:
        if self.kind == "transfer":
            return self.note or "账户转账"
        return self.payee or self.category_name or KIND_LABELS[self.kind]

    @property
    def account_display(self) -> str:
        if self.kind == "transfer":
            return f"{self.account_name} → {self.to_account_name}"
        return self.account_name

    @property
    def has_splits(self) -> bool:
        return bool(self.splits)

    @property
    def split_total(self) -> int:
        return sum(split.amount for split in self.splits)

    @property
    def tag_names(self) -> list[str]:
        return [tag.name for tag in self.tags]

    @property
    def is_refund(self) -> bool:
        return self.refund_of_id is not None


@dataclass(frozen=True)
class TransactionBalance:
    """Account balances immediately after a transaction was posted."""

    account_balance: int
    to_account_balance: int | None = None


@dataclass(frozen=True)
class MonthStats:
    month: str
    income: int
    expense: int
    net: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "net", self.income - self.expense)

    @property
    def savings_rate(self) -> float:
        if self.income <= 0:
            return 0.0
        return round(self.net / self.income * 100, 1)


@dataclass(frozen=True)
class FixedAsset:
    id: int
    name: str
    type: str
    purchase_price: int
    current_value: int
    valuation_date: str
    currency: str = "CNY"
    note: str = ""
    created_at: str = ""

    @property
    def type_label(self) -> str:
        return FIXED_ASSET_TYPE_META[self.type]["label"]

    @property
    def icon_name(self) -> str:
        return FIXED_ASSET_TYPE_META[self.type]["icon"]

    @property
    def gain(self) -> int:
        return self.current_value - self.purchase_price

    @property
    def gain_rate(self) -> float:
        if self.purchase_price <= 0:
            return 0.0
        return round(self.gain / self.purchase_price * 100, 1)


@dataclass(frozen=True)
class NetWorth:
    account_assets: int
    liabilities: int
    fixed_assets: int = 0
    fixed_asset_count: int = 0
    net: int = field(init=False)
    liability_ratio: float = field(init=False)
    asset_accounts: int = 0
    liability_accounts: int = 0

    @property
    def assets(self) -> int:
        return self.account_assets + self.fixed_assets

    def __post_init__(self) -> None:
        object.__setattr__(self, "net", self.assets - self.liabilities)
        total = self.assets + self.liabilities
        object.__setattr__(
            self, "liability_ratio", round(self.liabilities / total * 100, 1) if total else 0.0
        )


@dataclass(frozen=True)
class NetWorthPoint:
    month: str
    assets: int
    liabilities: int
    net: int


@dataclass(frozen=True)
class CategorySpend:
    category_id: int
    name: str
    color: str
    amount: int


@dataclass(frozen=True)
class RangeReport:
    """Totals and breakdowns for an arbitrary date range."""

    start_date: str
    end_date: str
    income: int
    expense: int
    previous_income: int
    previous_expense: int
    year_income: int
    year_expense: int
    breakdown: tuple[CategorySpend, ...] = ()
    trend: tuple[MonthStats, ...] = ()

    @property
    def net(self) -> int:
        return self.income - self.expense

    @property
    def savings_rate(self) -> float:
        if self.income <= 0:
            return 0.0
        return round(self.net / self.income * 100, 1)

    @staticmethod
    def change(current: int, previous: int) -> float | None:
        if previous == 0:
            return None
        return round((current - previous) / abs(previous) * 100, 1)


@dataclass(frozen=True)
class BudgetLine:
    id: int
    month: str
    category_id: int  # 0 means the whole month
    name: str
    color: str
    amount: int
    spent: int
    rollover: int = 0
    rollover_enabled: bool = False

    @property
    def is_overall(self) -> bool:
        return self.category_id == 0

    @property
    def available(self) -> int:
        return self.amount + self.rollover

    @property
    def remaining(self) -> int:
        return self.available - self.spent

    @property
    def ratio(self) -> float:
        return self.spent / self.available if self.available else 0.0


@dataclass(frozen=True)
class PayeeSpend:
    payee: str
    amount: int
    count: int


@dataclass(frozen=True)
class CategoryRule:
    """A payee keyword that fills the category (and tags) automatically."""

    id: int
    pattern: str
    kind: str
    category_id: int
    category_name: str = ""
    category_color: str = ""
    tags: tuple[str, ...] = ()
    hit_count: int = 0
    created_at: str = ""

    @property
    def tag_text(self) -> str:
        return "、".join(self.tags)


@dataclass
class TransactionFilter:
    month: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    kind: str | None = None
    category_id: int | None = None
    account_id: int | None = None
    tag_id: int | None = None
    search: str = ""
    limit: int = 500


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.imported > 0
