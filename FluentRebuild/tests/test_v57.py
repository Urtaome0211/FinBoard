"""Tests for 5.7 additions: auto-post, rule filters, alerts, health, forecast."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from finboard_fluent.core.database import SCHEMA_VERSION, Database
from finboard_fluent.core.dates import month_of, today_iso
from finboard_fluent.core.repository import Repository
from finboard_fluent.core.security import (
    SecurityError,
    make_recovery_record,
    recovery_configured,
    unwrap_master,
)
from finboard_fluent.core.service import FinanceService


class V57Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Database(Path(self.tmp.name) / "v57.db")
        self.repo = Repository(self.db)
        self.svc = FinanceService(self.repo)
        self.bank = self.repo.add_account("工资卡", "debit", 5_000_000)
        self.food = self.repo.find_category("餐饮", "expense").id
        self.day = today_iso()
        self.month = month_of(self.day)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_is_20(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 20)
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 20)

    def test_recovery_key_roundtrip(self) -> None:
        master = "ab" * 32
        record, code = make_recovery_record(master)
        config = {"encrypted": True, "recovery": record}
        self.assertTrue(recovery_configured(config))
        self.assertEqual(unwrap_master(config, code), master)
        self.assertEqual(unwrap_master(config, code.lower().replace("-", " ")), master)
        with self.assertRaises(SecurityError):
            unwrap_master(config, "AAAA-BBBB-CCCC-DDDD")
        with self.assertRaises(SecurityError):
            unwrap_master({}, code)

    def test_month_of_accepts_iso_string(self) -> None:
        self.assertEqual(month_of("2026-11-19"), "2026-11")

    def test_auto_post_only_flagged_rules(self) -> None:
        self.repo.add_recurring(
            name="房租", kind="expense", amount=200_000, account_id=self.bank,
            category_id=self.food, frequency="monthly", start_date="2026-01-05", auto_post=True,
        )
        self.repo.add_recurring(
            name="会员费", kind="expense", amount=3_000, account_id=self.bank,
            category_id=self.food, frequency="monthly", start_date="2026-01-05",
        )
        posted = self.svc.auto_post_recurring("2026-11-19")
        self.assertEqual(posted, 11)
        rules = {r.name: r for r in self.repo.recurring_rules()}
        self.assertEqual(rules["会员费"].next_date, "2026-01-05")
        self.assertTrue(all(t.note == "房租" for t in self.repo.transactions()))
        self.assertEqual(len(self.repo.transactions()), 11)

    def test_auto_post_is_idempotent_for_same_day(self) -> None:
        self.repo.add_recurring(
            name="房租", kind="expense", amount=100_000, account_id=self.bank,
            category_id=self.food, frequency="monthly", start_date="2026-11-01", auto_post=True,
        )
        self.assertEqual(self.svc.auto_post_recurring("2026-11-19"), 1)
        self.assertEqual(self.svc.auto_post_recurring("2026-11-19"), 0)

    def test_category_rule_amount_and_account_filters(self) -> None:
        self.repo.add_category_rule(
            "咖啡", "expense", self.food, amount_min=1_000, amount_max=5_000, account_id=self.bank,
        )
        self.assertIsNotNone(
            self.repo.match_category_rule("星巴克咖啡", "expense", amount=3_000, account_id=self.bank)
        )
        self.assertIsNone(
            self.repo.match_category_rule("星巴克咖啡", "expense", amount=9_000, account_id=self.bank)
        )
        self.assertIsNone(
            self.repo.match_category_rule("星巴克咖啡", "expense", amount=3_000, account_id=None)
        )
        other = self.repo.add_account("现金卡", "debit", 0)
        self.assertIsNone(
            self.repo.match_category_rule("星巴克咖啡", "expense", amount=3_000, account_id=other)
        )

    def test_category_rule_without_filters_matches_anything(self) -> None:
        self.repo.add_category_rule("地铁", "expense", self.food)
        self.assertIsNotNone(
            self.repo.match_category_rule("地铁通勤", "expense", amount=123, account_id=self.bank)
        )

    def test_category_rule_rejects_bad_range(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.add_category_rule("咖啡", "expense", self.food, amount_min=5_000, amount_max=1_000)
        with self.assertRaises(ValueError):
            self.repo.add_category_rule("咖啡", "expense", self.food, amount_max=-1)

    def test_rule_update_clears_filters(self) -> None:
        rule_id = self.repo.add_category_rule("咖啡", "expense", self.food, amount_max=500)
        self.repo.update_category_rule(rule_id, amount_max=None)
        rule = self.repo.get_category_rule(rule_id)
        self.assertIsNone(rule.amount_max)

    def test_notifications_are_idempotent_and_mark_read(self) -> None:
        self.repo.add_recurring(
            name="会员费", kind="expense", amount=3_000, account_id=self.bank,
            category_id=self.food, frequency="monthly", start_date="2026-11-01",
        )
        first = self.svc.refresh_alerts("2026-11-19")
        second = self.svc.refresh_alerts("2026-11-19")
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(self.svc.unread_notifications(), 1)
        self.svc.mark_all_notifications_read()
        self.assertEqual(self.svc.unread_notifications(), 0)

    def test_refresh_alerts_covers_budget_receivable_and_goal(self) -> None:
        self.repo.upsert_budget(self.month, self.food, 100)
        self.repo.add_transaction(date=self.day, kind="expense", amount=500, account_id=self.bank, category_id=self.food)
        self.repo.add_receivable(direction="receivable", counterparty="张三", amount=10_000,
                                 date="2019-12-01", due_date="2020-01-01")
        self.repo.add_savings_goal("旅行", 1_000_000, target_date="2020-12-31")
        created = self.svc.refresh_alerts(self.day)
        self.assertEqual(created, 3)
        kinds = {n.kind for n in self.svc.notifications()}
        self.assertEqual(kinds, {"budget", "overdue", "goal"})

    def test_copy_budgets_only_fills_missing(self) -> None:
        self.repo.upsert_budget("2026-10", self.food, 1_000)
        self.repo.upsert_budget("2026-11", self.food, 2_000)
        self.assertEqual(self.svc.copy_budgets("2026-10", "2026-11"), 0)
        self.assertEqual(self.svc.copy_budgets("2026-10", "2027-01"), 1)
        lines = self.repo.budget_lines("2027-01")
        self.assertEqual(lines[0].amount, 1_000)

    def test_savings_goal_forecast_on_track(self) -> None:
        goal = self.repo.add_savings_goal("旅行", 500_000, target_date="2030-12-31")
        self.repo.add_transaction(date=self.day, kind="income", amount=3_000_000, account_id=self.bank,
                                  category_id=self.repo.find_category("工资", "income").id)
        forecast = self.svc.savings_goal_forecast(goal)
        self.assertEqual(forecast["remaining"], 500_000)
        self.assertGreater(forecast["monthly_rate"], 0)
        self.assertEqual(forecast["months"], 1)
        self.assertTrue(forecast["on_track"])

    def test_savings_goal_forecast_without_surplus(self) -> None:
        goal = self.repo.add_savings_goal("旅行", 500_000, target_date="2030-12-31")
        forecast = self.svc.savings_goal_forecast(goal)
        self.assertIsNone(forecast["months"])
        self.assertEqual(forecast["projected_date"], "")
        self.assertFalse(forecast["on_track"])

    def test_health_checks_shape(self) -> None:
        checks = {item["key"]: item for item in self.svc.health_checks()}
        self.assertEqual(
            set(checks),
            {"uncategorized", "duplicates", "overdue_receivables", "stale_prices", "over_budget"},
        )
        for item in checks.values():
            self.assertIn("label", item)
            self.assertIn("level", item)
            self.assertGreaterEqual(item["count"], 0)

    def test_view_state_and_benchmark_roundtrip(self) -> None:
        self.svc.set_view_state("transactions.month", "2026-11")
        self.assertEqual(self.svc.view_state("transactions.month"), "2026-11")
        self.svc.set_benchmark_rate_bp(300)
        self.assertEqual(self.svc.benchmark_rate_bp(), 300)
