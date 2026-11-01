from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.rates import RateSnapshot
from finboard.core.repository import Repository


class FixedAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.account = self.repo.add_account("储蓄卡", "debit", 100_000)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_and_net_worth(self) -> None:
        self.assertEqual(self.db.conn.execute("PRAGMA user_version").fetchone()[0], 13)
        self.repo.add_fixed_asset(
            "自住房",
            "property",
            5_000_000,
            6_000_000,
            "2026-10-31",
        )
        worth = self.repo.net_worth()
        self.assertEqual(worth.account_assets, 100_000)
        self.assertEqual(worth.fixed_assets, 6_000_000)
        self.assertEqual(worth.fixed_asset_count, 1)
        self.assertEqual(worth.assets, 6_100_000)
        self.assertEqual(worth.net, 6_100_000)

    def test_crud_and_gain(self) -> None:
        asset_id = self.repo.add_fixed_asset(
            "家用车", "vehicle", 180_000, 120_000, "2026-10-31", note="旧车"
        )
        asset = self.repo.get_fixed_asset(asset_id)
        self.assertEqual(asset.gain, -60_000)
        self.assertEqual(asset.gain_rate, -33.3)
        self.repo.update_fixed_asset(
            asset_id,
            name="家用车",
            type_="vehicle",
            purchase_price=180_000,
            current_value=150_000,
            valuation_date="2026-11-01",
            note="更新",
        )
        self.assertEqual(self.repo.get_fixed_asset(asset_id).current_value, 150_000)
        self.repo.delete_fixed_asset(asset_id)
        self.assertEqual(self.repo.fixed_assets(), [])

    def test_foreign_asset_uses_valuation_rate(self) -> None:
        self.repo.rates.save(RateSnapshot(date="2026-10-31", rates={"USD": 0.15}))
        asset_id = self.repo.add_fixed_asset(
            "海外房产",
            "property",
            10_000,
            10_000,
            "2026-10-31",
            currency="USD",
        )
        asset = self.repo.get_fixed_asset(asset_id)
        self.assertEqual(asset.current_value, 10_000)
        self.assertEqual(self.repo.fixed_asset_value(), 66_667)
        self.assertEqual(self.repo.net_worth().fixed_assets, 66_667)

    def test_fixed_assets_do_not_change_cash_flow(self) -> None:
        before = self.repo.cash_flow_forecast(months=3, start_month="2026-11")
        self.repo.add_fixed_asset(
            "自住房", "property", 10_000_000, 12_000_000, "2026-10-31"
        )
        after = self.repo.cash_flow_forecast(months=3, start_month="2026-11")
        self.assertEqual(before[0].ending_cash, after[0].ending_cash)
        self.assertEqual(self.repo.liquid_balance(), 100_000)

    def test_duplicate_name_is_allowed_but_get_missing_fails(self) -> None:
        self.repo.add_fixed_asset("房产", "property", 1, 1, "2026-10-31")
        self.repo.add_fixed_asset("房产", "property", 2, 2, "2026-10-31")
        self.assertEqual(len(self.repo.fixed_assets()), 2)
        with self.assertRaises(ValueError):
            self.repo.get_fixed_asset(999_999)


if __name__ == "__main__":
    unittest.main()
