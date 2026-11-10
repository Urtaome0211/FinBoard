"""Optional market quote lookup.

The app is local-first: quotes are only fetched when the user asks for them,
or when automatic refresh is enabled in Settings.  The provider is Tencent's
public quote endpoint, which returns a compact GBK-encoded payload.  Everything
here is network-only and returns integer cents, like the rest of the app.

Tencent covers mainland A-shares, Hong Kong and US tickers.  US codes are
prefixed with ``us`` (``usSCHD``), HK codes with ``hk`` (``hk00700``), and the
provider reports the currency in the quote payload.  Symbols entered by hand
can use a bare code (``600000``, ``SCHD``), an exchange prefix
(``SH600000``, ``US.SCHD``) or a suffix (``600000.SH``, ``SCHD.US``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_QUOTE_URL = "https://qt.gtimg.cn/q="
_LINE = re.compile(r'v_([a-zA-Z0-9.]+)="([^"]*)"')
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}

# Currencies the Tencent quote feed can price.  A holding in any other
# currency is left untouched rather than being silently mis-priced.
QUOTE_CURRENCIES = frozenset({"CNY", "USD", "HKD"})


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


def _with_prefix(prefix: str, body: str) -> str:
    """Canonicalise an exchange prefix plus code body."""
    prefix = prefix.lower()
    body = str(body or "").strip().upper()
    if not body:
        return ""
    if prefix in ("sh", "sz", "bj"):
        digits = re.sub(r"\D", "", body)
        if len(digits) != 6:
            return ""
        return f"{prefix}{digits}"
    if prefix == "hk":
        digits = re.sub(r"\D", "", body)
        if not 1 <= len(digits) <= 5:
            return ""
        return f"hk{digits.zfill(5)}"
    if prefix == "us":
        ticker = body.replace(" ", "").strip(".-")
        if not _US_TICKER.fullmatch(ticker):
            return ""
        return f"us{ticker}"
    return ""


def normalize_symbol(raw: str) -> str:
    """Return a provider code such as ``sh600000``, ``hk00700`` or ``usSCHD``.

    Accepts bare codes, exchange prefixes and common suffixes.  US tickers are
    letters (or letters with a dot/dash), HK codes are padded to five digits.
    """
    text = str(raw or "").strip().upper().replace(" ", "")
    if not text:
        return ""
    text = text.replace("：", ":").replace("／", "/")

    # Exchange prefix: SH600000, SH.600000, US.SCHD, HK:00700.
    prefixed = re.match(r"^(SH|SZ|BJ|HK|US)[.:\-_/]?(.+)$", text)
    if prefixed:
        return _with_prefix(prefixed.group(1), prefixed.group(2))

    # Exchange suffix: 600000.SH, 510300.SS, SCHD.US, 00700.HK.
    suffixed = re.match(r"^(.+?)[.:\-_/](SH|SS|SZ|BJ|HK|US)$", text)
    if suffixed:
        prefix = "sh" if suffixed.group(2) == "SS" else suffixed.group(2)
        return _with_prefix(prefix, suffixed.group(1))

    if text.isdigit():
        if len(text) in (3, 4, 5):
            return f"hk{text.zfill(5)}"
        if len(text) != 6:
            return ""
        if text[0] in "569":
            return f"sh{text}"
        if text[0] in "0123":
            return f"sz{text}"
        if text[0] in "48":
            return f"bj{text}"
        return ""

    # A bare US ticker: SCHD, INTC, BRK.B.
    if _US_TICKER.fullmatch(text):
        return f"us{text}"
    return ""


def _quote_currency(provider: str, fields: list[str]) -> str:
    declared = fields[35].strip().upper() if len(fields) > 35 else ""
    if declared in QUOTE_CURRENCIES:
        return declared
    if provider.startswith("us"):
        return "USD"
    if provider.startswith("hk"):
        return "HKD"
    return "CNY"


def _quote_timestamp(fields: list[str]) -> str:
    raw = fields[30].strip() if len(fields) > 30 else ""
    if not raw:
        return ""
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
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
        quotes.append(
            Quote(
                symbol=code,
                name=name,
                price=price,
                currency=_quote_currency(code, fields),
                updated_at=_quote_timestamp(fields),
            )
        )
    return quotes


def fetch_quotes(symbols: list[str], *, timeout: float = 6.0) -> list[Quote]:
    """Fetch quotes for the given symbols.

    Invalid symbols are skipped.  Raises :class:`QuoteError` when the provider
    cannot be reached or returns no usable quote.
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
