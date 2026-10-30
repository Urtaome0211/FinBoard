"""Money utilities.

Every monetary value in FinBoard is stored as an **integer number of cents**.
This avoids binary floating point rounding errors in balances, budgets and
aggregations.  Parsing and formatting happen only at the UI/CSV boundary.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

#: 999,999,999.99 — a sane upper bound that still fits comfortably in SQLite.
MAX_AMOUNT_CENTS = 99_999_999_999

CURRENCIES: dict[str, dict[str, str]] = {
    "CNY": {"symbol": "¥", "name": "人民币"},
    "USD": {"symbol": "$", "name": "美元"},
    "EUR": {"symbol": "€", "name": "欧元"},
    "GBP": {"symbol": "£", "name": "英镑"},
    "HKD": {"symbol": "HK$", "name": "港币"},
    "JPY": {"symbol": "¥", "name": "日元"},
}
DEFAULT_CURRENCY = "CNY"


def currency_symbol(code: str) -> str:
    """Return the display symbol for an ISO-ish currency code."""
    return CURRENCIES.get(code, CURRENCIES[DEFAULT_CURRENCY])["symbol"]


def parse_amount(value: str | int | Decimal) -> int:
    """Parse a user-entered amount into integer cents.

    Accepts values such as ``"1,280.50"``, ``"¥ 45"`` or ``"12.345"``.
    Raises :class:`ValueError` with a human readable Chinese message.
    """
    if isinstance(value, bool):
        raise ValueError("金额格式不正确")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, Decimal):
        text = str(value)
    elif value is None:
        raise ValueError("请输入金额")
    else:
        text = unicodedata.normalize("NFKC", str(value)).strip()

    cleaned = text
    for symbol in ("¥", "￥", "$", "€", "£", ",", "，", " "):
        cleaned = cleaned.replace(symbol, "")
    if not cleaned:
        raise ValueError("请输入金额")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if cleaned.startswith("-"):
        raise ValueError("金额不能为负数")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("金额格式不正确") from None
    if not amount.is_finite():
        raise ValueError("金额格式不正确")

    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValueError("金额必须大于 0")

    cents = int(amount * 100)
    if cents > MAX_AMOUNT_CENTS:
        raise ValueError("金额超出可记录范围")
    return cents


def parse_signed_amount(value: str | int | Decimal, *, allow_zero: bool = True) -> int:
    """Parse an opening balance: negative values and zero are allowed."""
    if isinstance(value, bool):
        raise ValueError("金额格式不正确")
    if value is None:
        raise ValueError("请输入金额")
    text = unicodedata.normalize("NFKC", str(value)).strip()
    cleaned = text
    for symbol in ("¥", "￥", "$", "€", "£", ",", "，", " "):
        cleaned = cleaned.replace(symbol, "")
    if not cleaned:
        raise ValueError("请输入金额")
    sign = 1
    if cleaned[0] in "+-":
        sign = -1 if cleaned[0] == "-" else 1
        cleaned = cleaned[1:]
    if not cleaned:
        raise ValueError("金额格式不正确")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("金额格式不正确") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("金额格式不正确")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount == 0 and not allow_zero:
        raise ValueError("金额必须大于 0")
    cents = int(amount * 100) * sign
    if abs(cents) > MAX_AMOUNT_CENTS:
        raise ValueError("金额超出可记录范围")
    return cents


def format_cents(    cents: int,
    symbol: str = "¥",
    *,
    plus: bool = False,
    decimals: bool = True,
) -> str:
    """Format integer cents as ``¥1,234.50`` (or ``-¥1,234.50``)."""
    cents = int(cents)
    sign = "-" if cents < 0 else ("+" if plus and cents > 0 else "")
    whole, fraction = divmod(abs(cents), 100)
    if decimals:
        return f"{sign}{symbol}{whole:,}.{fraction:02d}"
    return f"{sign}{symbol}{whole:,}"


def format_signed_cents(cents: int, symbol: str = "¥") -> str:
    """Format a value with an explicit ``+`` for positive amounts."""
    return format_cents(cents, symbol, plus=True)


def format_compact(cents: int, symbol: str = "¥") -> str:
    """Compact Chinese-style amount for chart axes: ``1.8万`` / ``860``."""
    value = abs(int(cents)) / 100
    sign = "-" if cents < 0 else ""
    if value >= 100_000_000:
        text = f"{value / 100_000_000:.2f}".rstrip("0").rstrip(".") + "亿"
    elif value >= 10_000:
        text = f"{value / 10_000:.1f}".rstrip("0").rstrip(".") + "万"
    elif value >= 1_000:
        text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    else:
        text = f"{value:.0f}"
    return f"{sign}{symbol}{text}"


def percentage(part: int, total: int, digits: int = 1) -> float:
    """Return ``part / total * 100`` rounded for display, or 0 for empty totals."""
    if not total:
        return 0.0
    return round(part / total * 100, digits)


def format_percentage(part: int, total: int, digits: int = 1) -> str:
    return f"{percentage(part, total, digits):.{digits}f}%"


MAX_QUANTITY_UNITS = 10**13


def parse_quantity(value: str | int | Decimal) -> int:
    """Parse a share/unit quantity into millionths (6 decimal places)."""
    if isinstance(value, bool):
        raise ValueError("数量格式不正确")
    if isinstance(value, int):
        units = value * 1_000_000
    else:
        raw = unicodedata.normalize("NFKC", str(value)).strip().replace(",", "")
        if not raw:
            raise ValueError("请输入数量")
        if raw.startswith("-"):
            raise ValueError("数量必须大于 0")
        try:
            units = int(
                (Decimal(raw) * Decimal(1_000_000)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("数量格式不正确") from exc
    if units <= 0:
        raise ValueError("数量必须大于 0")
    if units > MAX_QUANTITY_UNITS:
        raise ValueError("数量超出可记录范围")
    return units


def format_quantity(units: int, *, max_decimals: int = 6) -> str:
    """Format millionth-units as a compact decimal quantity."""
    sign = "-" if units < 0 else ""
    whole, fraction = divmod(abs(int(units)), 1_000_000)
    text = f"{fraction:06d}"[:max_decimals].rstrip("0")
    return f"{sign}{whole:,}" + (f".{text}" if text else "")
