"""Small, deterministic analyses built on top of transactions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

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
