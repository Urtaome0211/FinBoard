"""Tests for the 4.3 savings and fixed-term deposit module."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.dates import add_months
from finboard.core.money import demand_deposit_interest
from finboard.core.repository import Repository
from finboard.core.service import FinanceService


class V43Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.tmp.name) / "v43.db")
        self.repo = Repository(self.db)
        self.service = FinanceService(self.repo)
        self.source_id = self.repo.add_account("储蓄卡", "debit", 200_000)
        self.destination_id = self.repo.add_account("目标卡", "debit", 20_000)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _add_deposit(self, **overrides):
        values = dict(
            name="一年期",
            principal=50_000,
            currency="CNY",
            annual_rate_bp=300,
            term_months=12,
            start_date="2026-01-15",
            early_rate_bp=35,
            source_account_id=self.source_id,
            destination_account_id=self.destination_id,
        )
        values.update(overrides)
        return self.repo.add_term_deposit(**values)

    def test_schema_v14_has_system_accounts_and_deposits(self) -> None:
        self.assertEqual(
            self.db.conn.execute("PRAGMA user_version").fetchone()[0], 14
        )
        account_columns = {
            row["name"]
            for row in self.db.conn.execute("PRAGMA table_info(accounts)")
        }
        tables = {
            row["name"]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertIn("is_system", account_columns)
        self.assertIn("term_deposits", tables)

    def test_deposit_lifecycle_and_shared_virtual_account(self) -> None:
        deposit_id = self._add_deposit()

        deposit = self.repo.get_term_deposit(deposit_id)
        self.assertEqual(deposit.maturity_date, "2027-01-15")
        self.assertEqual(deposit.maturity_interest, 1_500)
        self.assertTrue(deposit.is_active)
        self.assertGreaterEqual(deposit.progress, 0.0)
        self.assertLessEqual(deposit.progress, 100.0)

        virtual = self.repo.deposit_account("CNY")
        self.assertTrue(virtual.is_system)
        self.assertEqual(virtual.type, "investment")
        self.assertEqual(virtual.currency, "CNY")
        self.assertEqual(deposit.deposit_account_id, virtual.id)
        self.assertEqual(self.repo.account_balance(self.source_id), 150_000)
        self.assertEqual(self.repo.account_balance(self.destination_id), 20_000)
        self.assertEqual(self.repo.account_balance(virtual.id), 50_000)
        self.assertEqual(len(self.repo.term_deposits()), 1)

        result = self.repo.close_term_deposit(deposit_id, on="2027-01-15")
        self.assertEqual(result["reason"], "matured")
        self.assertEqual(result["interest"], 1_500)
        self.assertEqual(result["total"], 51_500)
        self.assertEqual(self.repo.account_balance(self.source_id), 150_000)
        self.assertEqual(self.repo.account_balance(self.destination_id), 71_500)
        self.assertEqual(self.repo.account_balance(virtual.id), 0)

        closed = self.repo.get_term_deposit(deposit_id)
        self.assertEqual(closed.status, "closed")
        self.assertEqual(closed.interest_paid, 1_500)
        self.assertEqual(self.repo.term_deposits(include_closed=False), [])
        stats = self.repo.month_stats("2027-01")
        self.assertEqual(stats.income, 1_500)
        self.assertEqual(stats.expense, 0)

    def test_early_withdrawal_uses_demand_rate(self) -> None:
        deposit_id = self._add_deposit(annual_rate_bp=600, early_rate_bp=35)
        expected = demand_deposit_interest(50_000, 35, 90)
        self.assertEqual(expected, 43)
        self.assertEqual(
            self.repo.get_term_deposit(deposit_id).early_interest("2026-04-15"),
            expected,
        )

        result = self.repo.close_term_deposit(deposit_id, on="2026-04-15")
        self.assertEqual(result["reason"], "early")
        self.assertEqual(result["interest"], expected)
        self.assertEqual(self.repo.account_balance(self.destination_id), 70_043)
        self.assertEqual(
            self.repo.get_term_deposit(deposit_id).close_reason, "early"
        )

    def test_deposit_can_return_to_the_source_account(self) -> None:
        deposit_id = self._add_deposit(destination_account_id=self.source_id)
        self.repo.close_term_deposit(deposit_id, on="2027-01-15")
        self.assertEqual(self.repo.account_balance(self.source_id), 201_500)

    def test_guards_and_system_account_protection(self) -> None:
        with self.assertRaises(ValueError):
            self._add_deposit(term_months=0)
        with self.assertRaises(ValueError):
            self._add_deposit(annual_rate_bp=10_001)
        with self.assertRaises(ValueError):
            self._add_deposit(principal=0)
        with self.assertRaises(ValueError):
            self._add_deposit(principal=200_001)

        credit_id = self.repo.add_account("信用卡", "credit", 0)
        with self.assertRaises(ValueError):
            self._add_deposit(source_account_id=credit_id)

        deposit_id = self._add_deposit()
        self.repo.close_term_deposit(deposit_id, on="2027-01-15")
        with self.assertRaises(ValueError):
            self.repo.close_term_deposit(deposit_id, on="2027-01-15")

        system = self.repo.deposit_account("CNY")
        with self.assertRaises(ValueError):
            self.repo.update_account(system.id, name="改名")
        with self.assertRaises(ValueError):
            self.repo.set_account_archived(system.id, True)
        with self.assertRaises(ValueError):
            self.repo.delete_account(system.id)

    def test_multi_currency_uses_one_virtual_account_per_currency(self) -> None:
        usd_source = self.repo.add_account(
            "美元储蓄", "debit", 100_000, currency="USD"
        )
        usd_destination = self.repo.add_account(
            "美元目标", "debit", 0, currency="USD"
        )
        deposit_id = self._add_deposit(
            name="美元定存",
            principal=10_000,
            currency="USD",
            annual_rate_bp=500,
            term_months=6,
            start_date="2026-02-01",
            source_account_id=usd_source,
            destination_account_id=usd_destination,
        )
        cny = self.repo.deposit_account("CNY")
        usd = self.repo.deposit_account("USD")
        self.assertNotEqual(cny.id, usd.id)
        self.assertEqual(usd.currency, "USD")
        self.assertIn("USD", usd.name)
        self.assertEqual(self.repo.get_term_deposit(deposit_id).maturity_date, "2026-08-01")
        self.assertEqual(
            self.repo.get_term_deposit(deposit_id).maturity_interest, 250
        )
        self.repo.close_term_deposit(deposit_id, on="2026-08-01")
        self.assertEqual(self.repo.account_balance(usd_destination), 10_250)

    def test_matured_list_and_month_arithmetic(self) -> None:
        deposit_id = self._add_deposit(
            start_date="2025-11-01", annual_rate_bp=300, term_months=12
        )
        matured = self.repo.matured_term_deposits()
        self.assertEqual([item.id for item in matured], [deposit_id])
        self.assertEqual(add_months("2026-01-31", 1), "2026-02-28")
        self.assertEqual(add_months("2026-01-31", 13), "2027-02-28")


if __name__ == "__main__":
    unittest.main()
