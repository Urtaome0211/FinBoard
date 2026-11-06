"""Investment trade and FIFO lot accounting tests (schema 16)."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository


class InvestmentLotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.account_id = self.repo.add_account("投资账户", "investment", 1_000_000)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_has_investment_tables(self) -> None:
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 17)
        tables = {
            row[0]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("investment_trades", tables)
        self.assertIn("investment_lots", tables)
        self.assertIn("investment_disposals", tables)

    def test_buy_creates_holding_and_lot(self) -> None:
        self.repo.record_investment_trade(
            self.account_id,
            kind="buy",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-01-05",
            quantity_units=1_000_000,
            price=10_000,
        )
        holding = self.repo.holdings(self.account_id)[0]
        self.assertEqual(holding.quantity_units, 1_000_000)
        self.assertEqual(holding.cost_price, 10_000)
        lots = self.repo.investment_lots(self.account_id)
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].remaining_units, 1_000_000)
        trades = self.repo.investment_trades(self.account_id)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].kind, "buy")

    def test_sell_uses_fifo_and_realizes_profit(self) -> None:
        self.repo.record_investment_trade(
            self.account_id,
            kind="buy",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-01-05",
            quantity_units=1_000_000,
            price=10_000,
            fee=100,
        )
        self.repo.record_investment_trade(
            self.account_id,
            kind="buy",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-02-05",
            quantity_units=1_000_000,
            price=12_000,
        )
        self.repo.record_investment_trade(
            self.account_id,
            kind="sell",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-03-05",
            quantity_units=1_500_000,
            price=15_000,
            fee=150,
        )
        holding = self.repo.holdings(self.account_id)[0]
        self.assertEqual(holding.quantity_units, 500_000)
        self.assertEqual(holding.cost_price, 12_000)
        self.assertEqual(holding.realized_profit, 6_250)
        disposals = self.repo.investment_disposals()
        self.assertEqual(len(disposals), 2)
        self.assertEqual(sum(item.realized for item in disposals), 6_250)
        lots = self.repo.investment_lots(self.account_id)
        self.assertEqual(sum(item.remaining_units for item in lots), 500_000)

    def test_sell_more_than_held_is_rejected(self) -> None:
        self.repo.record_investment_trade(
            self.account_id,
            kind="buy",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-01-05",
            quantity_units=1_000_000,
            price=10_000,
        )
        with self.assertRaisesRegex(ValueError, "超过"):
            self.repo.record_investment_trade(
                self.account_id,
                kind="sell",
                symbol="510300",
                name="沪深300ETF",
                trade_date="2026-02-05",
                quantity_units=2_000_000,
                price=10_000,
            )

    def test_v16_backfills_existing_holding(self) -> None:
        path = Path(self.tmp.name) / "migrate.db"
        db = Database(path)
        repo = Repository(db)
        account_id = repo.add_account("旧投资账户", "investment", 1_000_000)
        repo.add_holding(
            account_id,
            "旧持仓",
            symbol="OLD",
            quantity_units=2_000_000,
            cost_price=10_000,
            price=12_000,
        )
        db.close()
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE investment_disposals")
        conn.execute("DROP TABLE investment_lots")
        conn.execute("DROP TABLE investment_trades")
        conn.execute("PRAGMA user_version = 15")
        conn.commit()
        conn.close()
        db = Database(path)
        repo = Repository(db)
        trades = repo.investment_trades(account_id)
        lots = repo.investment_lots(account_id)
        self.assertEqual(repo.db.conn.execute("PRAGMA user_version").fetchone()[0], 17)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].kind, "buy")
        self.assertEqual(trades[0].quantity_units, 2_000_000)
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].remaining_units, 2_000_000)
        db.close()

    def test_dividend_updates_holding(self) -> None:
        self.repo.record_investment_trade(
            self.account_id,
            kind="buy",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-01-05",
            quantity_units=1_000_000,
            price=10_000,
        )
        self.repo.record_investment_trade(
            self.account_id,
            kind="dividend",
            symbol="510300",
            name="沪深300ETF",
            trade_date="2026-02-05",
            amount=5_000,
        )
        holding = self.repo.holdings(self.account_id)[0]
        self.assertEqual(holding.dividends, 5_000)


if __name__ == "__main__":
    unittest.main()
