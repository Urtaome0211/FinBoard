"""Tests for optional Tencent market quotes and price application."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finboard_fluent.core.database import Database
from finboard_fluent.core.quotes import Quote, QuoteError, normalize_symbol, parse_quotes
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.service import FinanceService


class QuoteParsingTests(unittest.TestCase):
    def test_normalize_symbols(self) -> None:
        self.assertEqual(normalize_symbol("600000"), "sh600000")
        self.assertEqual(normalize_symbol("000001"), "sz000001")
        self.assertEqual(normalize_symbol("510300"), "sh510300")
        self.assertEqual(normalize_symbol("830799"), "bj830799")
        self.assertEqual(normalize_symbol("hk00700"), "hk00700")
        self.assertEqual(normalize_symbol("AAPL"), "")
        self.assertEqual(normalize_symbol(""), "")

    def test_parse_tencent_payload(self) -> None:
        payload = (
            'v_sh600000="1~浦发银行~600000~10.25~10.00~10.10'
            '~0.25~2.50~10.11~10.24~10.00~10.25~12345~123456'
            '~0.00~0.00~10.25~10.25~10.25~10.25~0.00~0.00'
            '~10.25~10.25~10.25~10.25~0.00~0.00~0.00~0.00'
            '~20261104150000~0.25~2.50~10.25~10.00~10.10~10.11";'
        )
        quotes = parse_quotes(payload)
        self.assertEqual(len(quotes), 1)
        quote = quotes[0]
        self.assertEqual(quote.symbol, "sh600000")
        self.assertEqual(quote.name, "浦发银行")
        self.assertEqual(quote.price, 1025)
        self.assertEqual(quote.updated_at, "2026-11-04T15:00:00")

    def test_parse_skips_invalid_payload(self) -> None:
        self.assertEqual(parse_quotes("v_pv_none_match=1;"), [])


class QuoteServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo, "CNY")
        self.account = self.repo.add_account("证券账户", "investment", 100000)
        self.holding = self.repo.add_holding(
            self.account,
            "浦发银行",
            symbol="600000",
            quantity_units=1_000_000,
            cost_price=1000,
            price=1000,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_quote_symbols_and_apply(self) -> None:
        self.assertEqual(self.service.quote_symbols(), ["sh600000"])
        quotes = [Quote("sh600000", "浦发银行", 1200, updated_at="2026-11-04T15:00:00")]
        self.service.apply_market_quotes(quotes)
        self.assertEqual(self.repo.get_holding(self.holding).price, 1200)
        cached, fetched_at = self.service.quote_cache()
        self.assertEqual(len(cached), 1)
        self.assertEqual(cached[0].price, 1200)
        self.assertTrue(fetched_at)

    def test_refresh_quotes_uses_provider(self) -> None:
        fake = [Quote("sh600000", "浦发银行", 1300)]
        with patch("finboard_fluent.core.service.fetch_quotes", return_value=fake) as fetch:
            result = self.service.refresh_quotes()
        fetch.assert_called_once_with(["sh600000"])
        self.assertEqual(result[0].price, 1300)
        self.assertEqual(self.repo.get_holding(self.holding).price, 1300)

    def test_refresh_quotes_surfaces_provider_error(self) -> None:
        with patch(
            "finboard_fluent.core.service.fetch_quotes",
            side_effect=QuoteError("offline"),
        ):
            with self.assertRaises(QuoteError):
                self.service.refresh_quotes()

    def test_cache_survives_reload(self) -> None:
        self.service.apply_market_quotes([Quote("sh600000", "浦发银行", 1400)])
        raw = self.repo.meta_get("quotes/cache")
        data = json.loads(raw)
        self.assertEqual(data["quotes"][0]["price"], 1400)


if __name__ == "__main__":
    unittest.main()
