"""Small date helpers used across the data layer and the UI."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..i18n import is_english, month_name, weekday_name

MONTHS_CN = (
    "一月",
    "二月",
    "三月",
    "四月",
    "五月",
    "六月",
    "七月",
    "八月",
    "九月",
    "十月",
    "十一月",
    "十二月",
)
WEEKDAYS_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def today() -> date:
    return date.today()


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def parse_iso_day(value: str) -> date:
    """Parse ``YYYY-MM-DD``; raises :class:`ValueError` for bad input."""
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("日期格式应为 YYYY-MM-DD") from None


def normalize_day(value: str) -> str:
    """Accept ``2026/10/29`` as well and return ISO ``2026-10-29``."""
    text = str(value).strip().replace("/", "-").replace(".", "-")
    return parse_iso_day(text).isoformat()


def month_of(value: str | date) -> str:
    """Return ``YYYY-MM`` for an ISO date or a date object."""
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}"
    return parse_iso_day(value)[:7]


def parse_month(month: str) -> tuple[int, int]:
    try:
        year_text, month_text = str(month).split("-")
        year, month_number = int(year_text), int(month_text)
        if not 1 <= month_number <= 12 or not 1900 <= year <= 2200:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError("月份格式应为 YYYY-MM") from None
    return year, month_number


def month_bounds(month: str) -> tuple[str, str]:
    """Return ``(first_day, first_day_of_next_month)`` — an exclusive range."""
    year, month_number = parse_month(month)
    start = date(year, month_number, 1)
    if month_number == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month_number + 1, 1)
    return start.isoformat(), end.isoformat()


def month_label(month: str) -> str:
    year, month_number = parse_month(month)
    if is_english():
        return f"{month_name(month_number)} {year}"
    return f"{year}年{month_number}月"


def short_month_label(month: str) -> str:
    _, month_number = parse_month(month)
    if is_english():
        return month_name(month_number)
    return f"{month_number}月"


def shift_month(month: str, delta: int) -> str:
    year, month_number = parse_month(month)
    index = year * 12 + (month_number - 1) + int(delta)
    new_year, new_month = divmod(index, 12)
    return f"{new_year:04d}-{new_month + 1:02d}"


def recent_months(count: int, end_month: str | None = None) -> list[str]:
    """Chronologically ascending list of the last *count* months."""
    end_month = end_month or month_of(today())
    return [shift_month(end_month, offset) for offset in range(-(count - 1), 1)]


def month_choices(count: int = 18, end_month: str | None = None) -> list[str]:
    """Newest-first month choices, starting with *end_month* (default: now)."""
    end_month = end_month or month_of(today())
    count = max(1, int(count))
    return [shift_month(end_month, -offset) for offset in range(count)]


def day_label(value: str | date) -> str:
    day = value if isinstance(value, date) else parse_iso_day(value)
    if is_english():
        return f"{month_name(day.month)} {day.day}"
    return f"{day.month}月{day.day}日"


def weekday_label(value: str | date) -> str:
    day = value if isinstance(value, date) else parse_iso_day(value)
    if is_english():
        return weekday_name(day.weekday())
    return WEEKDAYS_CN[day.weekday()]


def full_date_label(value: str | date) -> str:
    day = value if isinstance(value, date) else parse_iso_day(value)
    if is_english():
        return f"{weekday_name(day.weekday())}, {month_name(day.month)} {day.day}, {day.year}"
    return f"{day.year}年{day.month}月{day.day}日 {WEEKDAYS_CN[day.weekday()]}"


def days_in_month(month: str) -> int:
    start, end = month_bounds(month)
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def last_n_days(count: int, end: date | None = None) -> list[date]:
    end = end or today()
    return [end - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
