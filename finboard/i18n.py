"""Tiny, dependency-free UI translation layer.

The source language is Simplified Chinese.  English strings live in
``finboard/locales/en.json`` and are looked up by their Chinese source text.
Widgets are translated in-place by :mod:`finboard.ui.localize`, so the code
does not need a ``tr()`` call around every literal.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DEFAULT_LANGUAGE = "zh"
LANGUAGES = (("zh", "中文"), ("en", "English"))

_current = DEFAULT_LANGUAGE
_strings: dict[str, str] = {}
_loaded = False

_EN_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_EN_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

DEFAULT_CATEGORY_EN = {
    "餐饮": "Dining",
    "购物": "Shopping",
    "交通": "Transport",
    "居住": "Housing",
    "娱乐": "Entertainment",
    "医疗": "Health",
    "教育": "Education",
    "通讯": "Utilities",
    "旅行": "Travel",
    "其他": "Other",
    "工资": "Salary",
    "奖金": "Bonus",
    "理财": "Investing",
    "兼职": "Side job",
}

ACCOUNT_TYPE_EN = {
    "现金": "Cash",
    "储蓄卡": "Debit card",
    "投资理财": "Investments",
    "信用卡": "Credit card",
    "贷款": "Loan",
}

# Dynamic strings are formatted before reaching the lookup.  These patterns
# cover the common shapes so composed labels do not stay Chinese.
_DYNAMIC = (
    (re.compile(r"^共 (\d+) 笔记录$"), r"\1 records"),
    (re.compile(r"^共 (\d+) 笔$"), r"\1 entries"),
    (re.compile(r"^(\d+) 笔记录$"), r"\1 records"),
    (re.compile(r"^(\d+) 笔$"), r"\1 entries"),
    (re.compile(r"^已用 (.*?) · 超支 (.*)$"), r"Used \1 · Over budget \2"),
    (re.compile(r"^已使用 (\d+)% · 已超支$"), r"\1% used · Over budget"),
    (re.compile(r"^已用 (.*)$"), r"Used \1"),
    (re.compile(r"^预算 (.*)$"), r"Budget \1"),
    (re.compile(r"^最大分类：(.*?) · (.*)$"), r"Top category: \1 · \2"),
    (re.compile(r"^超出预算 (.*)$"), r"Over budget by \1"),
    (re.compile(r"^当前 (\d+) 笔 · 收入 (.*?) · 支出 (.*)$"), r"\1 entries · Income \2 · Expenses \3"),
    (re.compile(r"^当前 (\d+) 笔 · 汇率不足，无法汇总$"), r"\1 entries · Exchange rate unavailable"),
    (re.compile(r"^(\d+) 个资产账户$"), r"\1 asset accounts"),
    (re.compile(r"^(\d+) 个负债账户$"), r"\1 liability accounts"),
    (re.compile(r"^资产 (.*?) · 负债 (.*)$"), r"Assets \1 · Liabilities \2"),
    (re.compile(r"^净资产 (.*)$"), r"Net worth \1"),
    (re.compile(r"^储蓄率 (.*)$"), r"Savings rate \1"),
    (re.compile(r"^已用 (.*?) · 剩余 (.*)$"), r"Used \1 · Remaining \2"),
    (re.compile(r"^已使用 (\d+)%$"), r"\1% used"),
    (re.compile(r"^超支 (.*)$"), r"Over budget \1"),
    (re.compile(r"^剩余 (.*)$"), r"Remaining \1"),
    (re.compile(r"^较上次 (.*)$"), r"vs. previous \1"),
    (re.compile(r"^(\d+) 天 · 日均可用 (.*)$"), r"\1 days · \2/day available"),
    (re.compile(r"^预计转入 (.*?) · 实际扣款 (.*)$"), r"Receives \1 · Actually deducted \2"),
    (re.compile(r"^账户入账 (.*)$"), r"Account amount \1"),
    (re.compile(r"^到账金额：(.*)$"), r"Received: \1"),
    (re.compile(r"^转入后余额 (.*)$"), r"Balance after transfer \1"),
    (re.compile(r"^动账后余额 (.*)$"), r"Balance after transaction \1"),
    (re.compile(r"^手续费 (.*)$"), r"Fee \1"),
    (re.compile(r"^(\d{4})年(\d{1,2})月$"), lambda m: f"{_EN_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日 周(.)$"), lambda m: f"{_EN_WEEKDAYS['一二三四五六日'.index(m.group(4))]}, {_EN_MONTHS[int(m.group(2)) - 1]} {int(m.group(3))}, {m.group(1)}"),
)


def _load() -> None:
    global _loaded, _strings
    if _loaded:
        return
    _loaded = True
    candidates = [Path(__file__).with_name("locales") / "en.json"]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.insert(0, Path(bundle_root) / "finboard" / "locales" / "en.json")
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict):
        _strings = {str(k): str(v) for k, v in data.items()}


def set_language(code: str) -> None:
    global _current
    _load()
    code = str(code or DEFAULT_LANGUAGE)
    _current = code if code in dict(LANGUAGES) else DEFAULT_LANGUAGE


def language() -> str:
    return _current


def is_english() -> bool:
    return _current == "en"


def translation_count() -> int:
    _load()
    return len(_strings)


def t(text: str, **kwargs) -> str:
    """Translate *text*; safe to call for amounts, names and empty strings."""
    if not text:
        return text
    _load()
    if not is_english():
        if kwargs:
            try:
                return str(text).format(**kwargs)
            except (KeyError, ValueError, IndexError):
                return str(text)
        return str(text)

    source = str(text)
    template = _strings.get(source)
    if template is None:
        template = source
        for pattern, replacement in _DYNAMIC:
            match = pattern.match(source)
            if not match:
                continue
            if callable(replacement):
                template = replacement(match)
            else:
                template = match.expand(replacement)
            break
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return template
    return template


def category_display(name: str) -> str:
    if not name:
        return name
    if is_english():
        return DEFAULT_CATEGORY_EN.get(name, t(name))
    return name


def account_type_display(label: str) -> str:
    if is_english():
        return ACCOUNT_TYPE_EN.get(label, t(label))
    return label


def month_label_en(year: int, month: int) -> str:
    return f"{_EN_MONTHS[month - 1]} {year}"


def month_name(month: int) -> str:
    return _EN_MONTHS[month - 1]


def weekday_name(index: int) -> str:
    return _EN_WEEKDAYS[index]


def today_label(month: int, day: int) -> str:
    if is_english():
        return f"Today {_EN_MONTHS[month - 1]} {day}"
    return f"今天 {month} 月 {day} 日"


def compact_amount(cents: int, symbol: str = "¥") -> str:
    """Compact amount for chart axes, with Chinese or English units."""
    value = abs(int(cents)) / 100
    sign = "-" if cents < 0 else ""
    if not is_english():
        if value >= 100_000_000:
            text = f"{value / 100_000_000:.2f}".rstrip("0").rstrip(".") + "亿"
        elif value >= 10_000:
            text = f"{value / 10_000:.1f}".rstrip("0").rstrip(".") + "万"
        elif value >= 1_000:
            text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
        else:
            text = f"{value:.0f}"
        return f"{sign}{symbol}{text}"
    if value >= 1_000_000_000:
        text = f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"
    elif value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    elif value >= 1_000:
        text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    else:
        text = f"{value:.0f}"
    return f"{sign}{symbol}{text}"


def currency_display(code: str, symbol: str, name: str) -> str:
    if not is_english():
        return f"{code} · {symbol} {name}"
    english = {
        "CNY": "Chinese yuan",
        "USD": "US dollar",
        "EUR": "Euro",
        "GBP": "Pound sterling",
        "HKD": "Hong Kong dollar",
        "JPY": "Japanese yen",
    }.get(code, name)
    return f"{code} · {symbol} {english}"
