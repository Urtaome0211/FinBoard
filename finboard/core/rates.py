"""Daily exchange rates and money conversion.

Rates are fetched from Frankfurter (the free ECB reference-rate API) and kept
locally in SQLite.  Every amount remains an integer number of cents; only the
conversion boundary uses ``Decimal`` so repeated arithmetic never accumulates
binary floating-point noise.

The table stores a single anchor: ``1 CNY = rate`` for each supported currency.
Cross rates are calculated through CNY.  When a requested day has no quote
(weekends and holidays) the most recent earlier quote is used.
"""

from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal, ROUND_HALF_UP

from .dates import now_iso, today_iso
from .database import Database
from .money import CURRENCIES

RATE_SOURCE = "Frankfurter · ECB"
RATE_BASE = "CNY"
RATE_URL = "https://api.frankfurter.app/latest?from=CNY&to=USD,EUR,GBP,JPY,HKD"
SUPPORTED_CURRENCIES: tuple[str, ...] = tuple(CURRENCIES)
META_CHECKED = "rates_checked_on"
META_ERROR = "rates_last_error"


class RateError(ValueError):
    """Raised when a conversion cannot be performed with the cached rates."""


@dataclass(frozen=True)
class RateSnapshot:
    date: str
    rates: dict[str, float]
    source: str = RATE_SOURCE
    fetched_at: str = field(default_factory=now_iso)

    @property
    def currencies(self) -> tuple[str, ...]:
        return tuple(sorted(self.rates))

    def summary(self) -> str:
        return f"{self.date} · {', '.join(self.currencies)}"


class RateStore:
    """Persistence and conversion around the ``exchange_rates`` table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ reads
    @property
    def conn(self):
        return self.db.conn

    def latest_date(self) -> str | None:
        row = self.conn.execute(
            "SELECT MAX(date) FROM exchange_rates"
        ).fetchone()
        return row[0] if row and row[0] else None

    def checked_on(self) -> str:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (META_CHECKED,)
        ).fetchone()
        return str(row[0]) if row else ""

    def last_error(self) -> str:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (META_ERROR,)
        ).fetchone()
        return str(row[0]) if row else ""

    def should_refresh(self) -> bool:
        return self.checked_on() != today_iso() or not self.has_rates()

    def has_rates(self) -> bool:
        return self.latest_date() is not None

    def rates_for(self, day: str | None = None) -> dict[str, float]:
        """Return the quote set effective on ``day`` (or the latest one)."""
        target = day or today_iso()
        row = self.conn.execute(
            "SELECT MAX(date) FROM exchange_rates WHERE date <= ?", (target,)
        ).fetchone()
        chosen = row[0] if row and row[0] else None
        if chosen is None:
            row = self.conn.execute(
                "SELECT MIN(date) FROM exchange_rates"
            ).fetchone()
            chosen = row[0] if row and row[0] else None
        if chosen is None:
            raise RateError("还没有汇率数据，请先在设置页更新汇率")
        rows = self.conn.execute(
            "SELECT currency, rate FROM exchange_rates WHERE date = ?", (chosen,)
        ).fetchall()
        rates = {str(code): float(rate) for code, rate in rows}
        rates[RATE_BASE] = 1.0
        return rates

    def snapshot(self, day: str | None = None) -> RateSnapshot:
        target = day or self.latest_date() or today_iso()
        return RateSnapshot(date=target, rates=self.rates_for(day), source=RATE_SOURCE)

    # ------------------------------------------------------------------ write
    def save(self, snapshot: RateSnapshot) -> None:
        if not snapshot.rates:
            raise RateError("汇率数据为空")
        clean: dict[str, float] = {RATE_BASE: 1.0}
        for code, raw in snapshot.rates.items():
            if code not in CURRENCIES:
                continue
            value = float(raw)
            if math.isfinite(value) and value > 0:
                clean[code] = value
        if set(clean) <= {RATE_BASE}:
            raise RateError("汇率数据无效")
        with self.db.transaction() as conn:
            for code, value in clean.items():
                conn.execute(
                    "INSERT INTO exchange_rates (date, currency, rate, source, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(date, currency) DO UPDATE SET"
                    " rate = excluded.rate, source = excluded.source,"
                    " fetched_at = excluded.fetched_at",
                    (snapshot.date, code, value, snapshot.source, snapshot.fetched_at),
                )
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (META_CHECKED, today_iso()),
            )
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, '')"
                " ON CONFLICT(key) DO UPDATE SET value = ''",
                (META_ERROR,),
            )

    def mark_failed(self, message: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (META_CHECKED, today_iso()),
            )
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (META_ERROR, str(message)[:300]),
            )

    # ------------------------------------------------------------------ fetch
    @staticmethod
    def fetch_latest(timeout: float = 9.0) -> RateSnapshot:
        request = urllib.request.Request(
            RATE_URL,
            headers={
                "User-Agent": "FinBoard/1.0 (+local personal finance)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network, HTTP, JSON — all become one message
            raise RateError(f"无法获取汇率：{exc}") from exc
        day = str(payload.get("date") or today_iso())
        raw = payload.get("rates") or {}
        rates = {str(k): float(v) for k, v in raw.items() if k in CURRENCIES}
        if not rates:
            raise RateError("汇率接口没有返回可用数据")
        return RateSnapshot(date=day, rates=rates)

    def refresh(self, *, force: bool = False) -> RateSnapshot | None:
        """Fetch and persist rates. Returns ``None`` when today's check is done."""
        if not force and not self.should_refresh():
            return None
        try:
            snapshot = self.fetch_latest()
        except RateError as exc:
            self.mark_failed(str(exc))
            raise
        self.save(snapshot)
        return snapshot

    # --------------------------------------------------------------- convert
    def convert(
        self,
        amount: int,
        from_currency: str,
        to_currency: str,
        day: str | None = None,
    ) -> int:
        """Convert integer cents between two supported currencies."""
        source = from_currency or RATE_BASE
        target = to_currency or RATE_BASE
        if source == target:
            return int(amount)
        for code in (source, target):
            if code not in CURRENCIES:
                raise RateError(f"不支持的币种：{code}")
        rates = self.rates_for(day)
        try:
            rate_from = Decimal(str(rates[source]))
            rate_to = Decimal(str(rates[target]))
        except KeyError as exc:
            raise RateError(f"缺少 {exc.args[0]} 的汇率，请先更新汇率") from None
        value = Decimal(int(amount)) / rate_from * rate_to
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_day_arg(value: date_type | str | None) -> str | None:
    """Small helper used by callers that may pass a date object."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date_type) else str(value)
