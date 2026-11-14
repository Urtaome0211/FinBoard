"""Small, deterministic analyses built on top of transactions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .dates import month_of, shift_month, today
from .models import Transaction


@dataclass(frozen=True)
class FixedCost:
    """A repeated monthly payment that looks like a subscription or bill."""

    payee: str
    category: str
    monthly: int
    count: int
    months: int
    annual: int
    last_date: str
    variation: float


def detect_fixed_costs(
    transactions: Iterable[Transaction],
    *,
    min_months: int = 3,
    tolerance: float = 0.2,
) -> list[FixedCost]:
    """Find payees charged in at least ``min_months`` distinct months.

    ``tolerance`` is the allowed spread between the cheapest and most
    expensive charge, relative to the average.  This catches subscriptions
    whose price changed slightly while ignoring one-off purchases.
    """
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        if txn.kind != "expense" or not txn.payee.strip() or txn.amount <= 0:
            continue
        groups[txn.payee.strip().casefold()].append(txn)

    found: list[FixedCost] = []
    for items in groups.values():
        months = {item.date[:7] for item in items}
        if len(months) < min_months:
            continue
        amounts = [item.amount for item in items]
        average = sum(amounts) // len(amounts)
        if average <= 0:
            continue
        spread = max(amounts) - min(amounts)
        variation = spread / average
        if variation > tolerance:
            continue
        last = max(items, key=lambda item: item.date)
        found.append(
            FixedCost(
                payee=last.payee.strip(),
                category=last.category_name,
                monthly=average,
                count=len(items),
                months=len(months),
                annual=average * 12,
                last_date=last.date,
                variation=variation,
            )
        )
    found.sort(key=lambda item: (-item.annual, item.payee.casefold()))
    return found


@dataclass(frozen=True)
class FinancialHealth:
    """A compact, explainable snapshot of the user's financial position."""

    month: str
    score: int
    grade: str
    savings_rate: float
    emergency_months: float
    debt_ratio: float
    fixed_ratio: float
    budget_ratio: float
    has_budget: bool
    income: int
    expense: int
    average_income: int
    average_expense: int
    liquid: int
    liabilities: int
    assets: int
    fixed_monthly: int
    top_category: str
    top_category_amount: int


def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def financial_health(repo, month: str | None = None) -> FinancialHealth:
    """Compute ratios and a 0-100 score using existing repository aggregates."""
    month = month or month_of(today())
    current = repo.month_stats(month)
    previous = shift_month(month, -1)
    history = repo.trend(3, end_month=previous)
    incomes = [point.income for point in history if point.income > 0]
    expenses = [point.expense for point in history if point.expense > 0]
    average_income = sum(incomes) // len(incomes) if incomes else current.income
    average_expense = sum(expenses) // len(expenses) if expenses else current.expense

    worth = repo.net_worth()
    liquid = repo.liquid_balance()
    fixed = detect_fixed_costs(repo.expense_history(12))
    fixed_monthly = sum(item.monthly for item in fixed)
    lines = repo.budget_lines(month)
    overall = next((line for line in lines if line.is_overall), None)
    has_budget = overall is not None and overall.amount > 0
    budget_ratio = (overall.spent / overall.available * 100) if has_budget and overall.available > 0 else 0.0

    emergency_months = (liquid / average_expense) if average_expense > 0 else 0.0
    debt_ratio = (worth.liabilities / worth.assets * 100) if worth.assets > 0 else 0.0
    fixed_ratio = (fixed_monthly / average_income * 100) if average_income > 0 else 0.0
    savings_rate = current.savings_rate

    score = 0.0
    score += min(30.0, max(0.0, savings_rate / 30 * 30))
    if emergency_months >= 6:
        score += 25
    elif emergency_months >= 3:
        score += 18
    elif emergency_months >= 1:
        score += 10
    elif emergency_months > 0:
        score += 5
    if debt_ratio <= 20:
        score += 20
    elif debt_ratio <= 40:
        score += 15
    elif debt_ratio <= 60:
        score += 8
    if fixed_ratio <= 30:
        score += 15
    elif fixed_ratio <= 50:
        score += 10
    elif fixed_ratio <= 70:
        score += 5
    if has_budget:
        score += 10 if budget_ratio <= 100 else 6 if budget_ratio <= 120 else 2
    else:
        score += 5
    score = int(round(min(100, max(0, score))))

    breakdown = repo.category_breakdown(month, "expense")
    top = breakdown[0] if breakdown else None
    return FinancialHealth(
        month=month,
        score=score,
        grade=_grade(score),
        savings_rate=savings_rate,
        emergency_months=round(emergency_months, 1),
        debt_ratio=round(debt_ratio, 1),
        fixed_ratio=round(fixed_ratio, 1),
        budget_ratio=round(budget_ratio, 1),
        has_budget=has_budget,
        income=current.income,
        expense=current.expense,
        average_income=average_income,
        average_expense=average_expense,
        liquid=liquid,
        liabilities=worth.liabilities,
        assets=worth.assets,
        fixed_monthly=fixed_monthly,
        top_category=top.name if top else "",
        top_category_amount=top.amount if top else 0,
    )
