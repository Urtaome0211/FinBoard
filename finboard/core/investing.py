"""Small investment analytics helpers."""

from __future__ import annotations

from datetime import date


def xirr(flows: list[tuple[date, int]]) -> float | None:
    """Return the annualized internal rate of return for dated cash flows.

    Amounts use the same signed integer cents as the rest of the app:
    money going out of the portfolio is negative, money coming back is
    positive.  ``None`` means the flows do not produce a meaningful rate
    (for example, all flows happen on one day or all have the same sign).
    """
    clean = [(day, int(amount)) for day, amount in flows if int(amount) != 0]
    if len(clean) < 2:
        return None
    if not any(amount < 0 for _, amount in clean):
        return None
    if not any(amount > 0 for _, amount in clean):
        return None
    origin = min(day for day, _ in clean)
    points = [
        ((day - origin).days / 365.0, amount) for day, amount in clean
    ]

    def npv(rate: float) -> float:
        base = 1.0 + rate
        try:
            return sum(amount / base**years for years, amount in points)
        except (OverflowError, ZeroDivisionError):
            return float("inf")

    low, high = -0.9999, 10.0
    low_value, high_value = npv(low), npv(high)
    # Expand the upper bound for very high-return short positions.
    for _ in range(40):
        if low_value * high_value <= 0:
            break
        high *= 2
        high_value = npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(120):
        middle = (low + high) / 2
        value = npv(middle)
        if abs(value) < 1e-9:
            return middle
        if low_value * value <= 0:
            high, high_value = middle, value
        else:
            low, low_value = middle, value
    return (low + high) / 2
