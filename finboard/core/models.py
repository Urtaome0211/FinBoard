"""Plain data models shared by the repository, service and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
class CategorySpend:
    category_id: int
    name: str
    color: str
    amount: int


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
