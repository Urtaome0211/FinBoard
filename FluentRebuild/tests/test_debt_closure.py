"""Debt closure: repayment records tied to principal and interest."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard_fluent.core.database import Database
from finboard_fluent.core.repository import Repository


class DebtClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.repo = Repository(self.db)
        self.bank = self.repo.add_account("工资卡", "debit", 1_000_000)
        self.loan = self.repo.add_account("房贷", "loan", -100_000)
        self.repo.save_debt(
            self.loan,
            kind="loan",
            principal=100_000,
            annual_rate_bp=490,
            term_months=12,
            start_date="2026-01-01",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def test_schema_has_debt_payments(self) -> None:
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 19)
        table = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='debt_payments'"
        ).fetchone()
        self.assertIsNotNone(table)

    def test_loan_payment_splits_interest_and_principal(self) -> None:
        result = self.repo.record_debt_payment(
            self.loan,
            amount=10_000,
            source_account_id=self.bank,
            paid_on="2026-11-04",
        )
        self.assertEqual(result["principal"], 9_592)
        self.assertEqual(result["interest"], 408)
        self.assertEqual(result["outstanding_after"], 90_408)
        self.assertEqual(self.repo.account_balance(self.bank), 990_000)
        self.assertEqual(self.repo.account_balance(self.loan), -90_408)
        payments = self.repo.debt_payments(self.loan)
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].amount, 10_000)
        self.assertEqual(self.repo.debt_paid_principal(self.loan), 9_592)
        self.assertEqual(self.repo.debt_paid_interest(self.loan), 408)
        kinds = {row.kind for row in self.repo.transactions()}
        self.assertEqual(kinds, {"transfer", "expense"})
        interest = next(
            row for row in self.repo.transactions() if row.kind == "expense"
        )
        self.assertEqual(interest.category_name, "利息支出")

    def test_credit_payment_has_no_interest(self) -> None:
        card = self.repo.add_account("信用卡", "credit", -50_000)
        self.repo.save_debt(
            card,
            kind="credit",
            credit_limit=200_000,
            annual_rate_bp=1800,
            billing_day=5,
            due_day=20,
        )
        result = self.repo.record_debt_payment(
            card, amount=20_000, source_account_id=self.bank
        )
        self.assertEqual(result["principal"], 20_000)
        self.assertEqual(result["interest"], 0)
        self.assertEqual(self.repo.account_balance(card), -30_000)

    def test_overpayment_and_missing_debt_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "超过剩余欠款|剩余本金"):
            self.repo.record_debt_payment(
                self.loan, amount=200_000, source_account_id=self.bank
            )
        with self.assertRaisesRegex(ValueError, "请先设置负债信息"):
            self.repo.record_debt_payment(
                self.bank, amount=100, source_account_id=self.bank
            )

    def test_interest_only_payment_keeps_principal(self) -> None:
        result = self.repo.record_debt_payment(
            self.loan, amount=408, source_account_id=self.bank
        )
        self.assertEqual(result["principal"], 0)
        self.assertEqual(result["interest"], 408)
        self.assertEqual(self.repo.account_balance(self.loan), -100_000)

    def test_source_must_be_a_funded_asset_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "还款来源"):
            self.repo.record_debt_payment(
                self.loan, amount=1_000, source_account_id=self.loan
            )
        poor = self.repo.add_account("零钱", "cash", 1_000)
        with self.assertRaisesRegex(ValueError, "余额不足"):
            self.repo.record_debt_payment(
                self.loan, amount=2_000, source_account_id=poor
            )


if __name__ == "__main__":
    unittest.main()
