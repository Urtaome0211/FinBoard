"""Optional market quote lookup.

The app is local-first: quotes are only fetched when the user asks for them,
or when automatic refresh is enabled in Settings.  The provider is Tencent's
public quote endpoint, which returns a compact GBK-encoded payload.  Everything
here is network-only and returns integer cents, like the rest of the app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_QUOTE_URL = "https://qt.gtimg.cn/q="
_LINE = re.compile(r'v_([a-zA-Z0-9]+)="([^"]*)"')
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}


class QuoteError(RuntimeError):
    """Raised when the quote provider cannot be reached or parsed."""


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    price: int
    currency: str = "CNY"
    updated_at: str = ""
    source: str = "tencent"

    @property
    def is_valid(self) -> bool:
        return bool(self.symbol) and self.price >= 0


def normalize_symbol(raw: str) -> str:
    """Return a provider code such as ``sh600000`` or ``sz000001``."""
    text = str(raw or "").strip().lower().replace(".", "")
    if not text:
        return ""
    if text[:2] in ("sh", "sz", "bj", "hk") and text[2:].isdigit():
        return text
    if not text.isdigit():
        return ""
    if len(text) == 5:
        return f"hk{text}"
    if len(text) != 6:
        return ""
    if text[0] in "569":
        return f"sh{text}"
    if text[0] in "0123":
        return f"sz{text}"
    if text[0] in "48":
        return f"bj{text}"
    return ""


def parse_quotes(payload: str) -> list[Quote]:
    """Parse the Tencent ``v_xxx="..."`` response."""
    quotes: list[Quote] = []
    for symbol, body in _LINE.findall(payload or ""):
        fields = body.split("~")
        if len(fields) < 5:
            continue
        code = normalize_symbol(symbol) or symbol.lower()
        name = fields[1].strip()
        price_text = fields[3].strip()
        if not name or not price_text:
            continue
        try:
            price = int(
                (Decimal(price_text) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        except (InvalidOperation, ValueError):
            continue
        if price <= 0:
            continue
        stamp = fields[30].strip() if len(fields) > 30 else ""
        updated_at = ""
        if len(stamp) >= 14 and stamp[:14].isdigit():
            try:
                updated_at = datetime.strptime(
                    stamp[:14], "%Y%m%d%H%M%S"
                ).isoformat(timespec="seconds")
            except ValueError:
                updated_at = ""
        quotes.append(
            Quote(
                symbol=code,
                name=name,
                price=price,
                currency="CNY",
                updated_at=updated_at,
            )
        )
    return quotes


def fetch_quotes(symbols: list[str], *, timeout: float = 6.0) -> list[Quote]:
    """Fetch quotes for the given symbols.

    Invalid or non-CNY symbols are simply skipped.  Raises :class:`QuoteError`
    when the provider cannot be reached or returns no usable quote.
    """
    codes: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        code = normalize_symbol(raw)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    if not codes:
        return []
    request = Request(_QUOTE_URL + ",".join(codes), headers=_HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise QuoteError(str(exc)) from exc
    try:
        text = payload.decode("gbk", errors="replace")
    except Exception as exc:  # pragma: no cover - defensive
        raise QuoteError("行情数据无法解码") from exc
    quotes = parse_quotes(text)
    if not quotes:
        raise QuoteError("行情服务没有返回有效数据")
    return quotes
