"""Loan, credit-card and debt-payoff calculations.

Everything here is computed from a small set of inputs; no schedule is stored
in the database.  Amounts are integer cents, rates are basis points (3.25% is
325), and dates are ISO ``YYYY-MM-DD`` strings.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .dates import add_months, normalize_day

MONTHS_PER_YEAR = 12
BASIS_POINTS = 10_000


@dataclass(frozen=True)
class Installment:
    number: int
    date: str
    payment: int
    principal: int
    interest: int
    balance: int


@dataclass(frozen=True)
class CreditCycle:
    statement_date: str
    due_date: str
    days_until_due: int


@dataclass(frozen=True)
class PayoffItem:
    name: str
    balance: int
    annual_rate_bp: int
    min_payment: int


@dataclass(frozen=True)
class PayoffRow:
    month: int
    payments: dict[str, int] = field(default_factory=dict)
    balances: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PayoffPlan:
    months: int
    total_interest: int
    order: tuple[str, ...]
    rows: tuple[PayoffRow, ...]


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _monthly_rate(annual_rate_bp: int) -> Decimal:
    return Decimal(int(annual_rate_bp)) / Decimal(BASIS_POINTS * MONTHS_PER_YEAR)


def _interest(balance: int, annual_rate_bp: int) -> int:
    return _round(Decimal(max(0, balance)) * _monthly_rate(annual_rate_bp))


def _clamped_date(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), last))


def amortization(
    principal: int,
    annual_rate_bp: int,
    term_months: int,
    start_date: str,
    method: str = "equal_payment",
) -> list[Installment]:
    """Build a monthly amortization schedule.

    ``equal_payment`` keeps the payment stable (等额本息);
    ``equal_principal`` keeps principal stable (等额本金).
    """
    principal = int(principal)
    term_months = int(term_months)
    if principal <= 0:
        raise ValueError("贷款本金必须大于 0")
    if term_months <= 0 or term_months > 600:
        raise ValueError("贷款期数必须在 1 到 600 之间")
    if annual_rate_bp < 0 or annual_rate_bp > 10000:
        raise ValueError("年利率应在 0% 到 100% 之间")
    if method not in ("equal_payment", "equal_principal"):
        raise ValueError("还款方式无效")
    start = normalize_day(start_date)

    rate = _monthly_rate(annual_rate_bp)
    payment = 0
    if method == "equal_payment":
        if rate == 0:
            payment = (principal + term_months - 1) // term_months
        else:
            factor = (Decimal(1) + rate) ** term_months
            payment = _round(principal * rate * factor / (factor - 1))

    rows: list[Installment] = []
    balance = principal
    base_principal = principal // term_months if method == "equal_principal" else 0
    for number in range(1, term_months + 1):
        interest = _interest(balance, annual_rate_bp)
        if number == term_months:
            principal_part = balance
        elif method == "equal_principal":
            principal_part = base_principal
        else:
            principal_part = payment - interest
            if principal_part <= 0:
                principal_part = max(1, principal - balance + 1)
        principal_part = min(balance, max(0, principal_part))
        due = balance + interest if number == term_months else principal_part + interest
        balance -= principal_part
        rows.append(
            Installment(
                number=number,
                date=add_months(start, number - 1),
                payment=due,
                principal=principal_part,
                interest=interest,
                balance=max(0, balance),
            )
        )
        if balance == 0:
            break
    return rows


def credit_cycle(
    billing_day: int | None,
    due_day: int | None,
    today: date | str | None = None,
) -> CreditCycle:
    """Return the latest statement and the next due date for a credit card."""
    if not billing_day or not due_day:
        raise ValueError("请先设置账单日和还款日")
    if not 1 <= int(billing_day) <= 28 or not 1 <= int(due_day) <= 28:
        raise ValueError("账单日和还款日必须在 1 到 28 之间")
    current = (
        date.fromisoformat(normalize_day(today))
        if today
        else date.today()
    )
    statement = _clamped_date(current.year, current.month, int(billing_day))
    if statement > current:
        year, month = (statement.year, statement.month - 1)
        if month == 0:
            year, month = year - 1, 12
        statement = _clamped_date(year, month, int(billing_day))
    due = _clamped_date(statement.year, statement.month, int(due_day))
    if due <= statement:
        year, month = statement.year, statement.month + 1
        if month == 13:
            year, month = year + 1, 1
        due = _clamped_date(year, month, int(due_day))
    if due < current:
        year, month = statement.year, statement.month + 1
        if month == 13:
            year, month = year + 1, 1
        statement = _clamped_date(year, month, int(billing_day))
        due = _clamped_date(statement.year, statement.month, int(due_day))
        if due <= statement:
            year, month = statement.year, statement.month + 1
            if month == 13:
                year, month = year + 1, 1
            due = _clamped_date(year, month, int(due_day))
    return CreditCycle(
        statement_date=statement.isoformat(),
        due_date=due.isoformat(),
        days_until_due=(due - current).days,
    )


def payoff_plan(
    items: list[PayoffItem],
    *,
    extra_monthly: int = 0,
    method: str = "avalanche",
) -> PayoffPlan:
    """Simulate debt payoff with the snowball or avalanche method."""
    if method not in ("snowball", "avalanche"):
        raise ValueError("还款策略无效")
    extra_monthly = max(0, int(extra_monthly))
    balances: dict[str, int] = {}
    rates: dict[str, int] = {}
    minimums: dict[str, int] = {}
    for item in items:
        if item.balance <= 0:
            continue
        name = item.name
        suffix = 2
        while name in balances:
            name = f"{item.name} ({suffix})"
            suffix += 1
        balances[name] = int(item.balance)
        rates[name] = max(0, int(item.annual_rate_bp))
        minimums[name] = max(0, int(item.min_payment))

    if not balances:
        return PayoffPlan(months=0, total_interest=0, order=(), rows=())

    if method == "avalanche":
        order = tuple(
            sorted(balances, key=lambda name: (-rates[name], balances[name], name))
        )
    else:
        order = tuple(
            sorted(balances, key=lambda name: (balances[name], -rates[name], name))
        )

    rows: list[PayoffRow] = []
    total_interest = 0
    month = 0
    while any(value > 0 for value in balances.values()):
        month += 1
        if month > 1200:
            raise ValueError("按当前还款额无法还清，请提高最低还款或额外还款")
        interest = {
            name: _interest(balance, rates[name])
            for name, balance in balances.items()
            if balance > 0
        }
        total_interest += sum(interest.values())
        payments: dict[str, int] = {}
        available = extra_monthly + sum(
            minimums[name] for name, balance in balances.items() if balance > 0
        )
        # First cover every minimum, including interest.
        for name in order:
            balance = balances.get(name, 0)
            if balance <= 0:
                continue
            owed = balance + interest[name]
            pay = min(owed, minimums[name], available)
            if pay > 0:
                available -= pay
                payments[name] = payments.get(name, 0) + pay
                balances[name] = max(0, owed - pay)
        # Then throw the extra money at the target debt.
        for name in order:
            if available <= 0:
                break
            balance = balances.get(name, 0)
            if balance <= 0:
                continue
            pay = min(balance, available)
            available -= pay
            payments[name] = payments.get(name, 0) + pay
            balances[name] = balance - pay
        if not payments:
            raise ValueError("按当前还款额无法还清，请提高最低还款或额外还款")
        rows.append(
            PayoffRow(
                month=month,
                payments={name: value for name, value in payments.items() if value},
                balances={name: value for name, value in balances.items() if value},
            )
        )
    return PayoffPlan(
        months=month,
        total_interest=total_interest,
        order=order,
        rows=tuple(rows),
    )
