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
class Category:
    id: int
    name: str
    kind: str
    color: str

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


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
    account_currency: str = "CNY"
    to_account_currency: str = "CNY"

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
class NetWorth:
    assets: int
    liabilities: int
    net: int = field(init=False)
    liability_ratio: float = field(init=False)
    asset_accounts: int = 0
    liability_accounts: int = 0

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

    @property
    def is_overall(self) -> bool:
        return self.category_id == 0

    @property
    def remaining(self) -> int:
        return self.amount - self.spent

    @property
    def ratio(self) -> float:
        return self.spent / self.amount if self.amount else 0.0


@dataclass(frozen=True)
class PayeeSpend:
    payee: str
    amount: int
    count: int


@dataclass
class TransactionFilter:
    month: str | None = None
    kind: str | None = None
    category_id: int | None = None
    account_id: int | None = None
    search: str = ""
    limit: int = 500


@dataclass
class ImportResult:
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.imported > 0
