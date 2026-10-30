"""Withdrawal-fee regression tests for Alipay and WeChat wallets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finboard.core.database import Database
from finboard.core.fees import calculate_withdrawal_fee, withdrawal_rule
from finboard.core.rates import RateSnapshot
from finboard.core.repository import Repository


class WithdrawalFeeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "fees.db")
        self.repo = Repository(self.db)
        self.alipay = self.repo.add_account("支付宝钱包", "debit", 200_000)
        self.wechat = self.repo.add_account("微信钱包", "debit", 200_000)
        self.bank = self.repo.add_account("银行储蓄卡", "debit", 0)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _transfer(self, source: int, amount: int, *, to: int | None = None):
        return self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=amount,
            account_id=source,
            to_account_id=to or self.bank,
        )

    def test_rule_detection_and_rounding(self) -> None:
        self.assertIsNotNone(withdrawal_rule("支付宝钱包"))
        self.assertIsNotNone(withdrawal_rule("支付宝"))
        self.assertIsNotNone(withdrawal_rule("微信钱包"))
        self.assertIsNone(withdrawal_rule("银行卡"))
        self.assertIsNone(withdrawal_rule("支付宝钱包", "USD"))
        self.assertEqual(calculate_withdrawal_fee("支付宝钱包", 100_000), 100)
        self.assertEqual(calculate_withdrawal_fee("微信钱包", 100_000), 100)
        self.assertEqual(calculate_withdrawal_fee("支付宝钱包", 12_345), 12)
        self.assertEqual(calculate_withdrawal_fee("支付宝钱包", 1), 10)
        self.assertEqual(calculate_withdrawal_fee("微信钱包", 1), 1)

    def test_alipay_fee_is_deducted_from_source(self) -> None:
        txn_id = self._transfer(self.alipay, 100_000)
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.fee, 100)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 99_900)
        self.assertEqual(self.repo.get_account(self.bank).balance, 100_000)

    def test_wechat_minimum_is_one_cent(self) -> None:
        txn_id = self._transfer(self.wechat, 100)
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.fee, 1)
        self.assertEqual(self.repo.get_account(self.wechat).balance, 199_899)
        self.assertEqual(self.repo.get_account(self.bank).balance, 100)

    def test_full_withdrawal_includes_fee_in_the_withdrawal(self) -> None:
        txn_id = self._transfer(self.alipay, 200_000)
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.fee, 200)
        self.assertTrue(txn.fee_included)
        self.assertEqual(txn.to_amount, 199_800)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 0)
        self.assertEqual(self.repo.get_account(self.bank).balance, 199_800)
        balance = self.repo.transaction_balances([txn_id])[txn_id]
        self.assertEqual(balance.account_balance, 0)
        self.assertEqual(balance.to_account_balance, 199_800)

    def test_partial_withdrawal_keeps_fee_separate(self) -> None:
        txn_id = self._transfer(self.alipay, 50_000)
        txn = self.repo.get_transaction(txn_id)
        self.assertFalse(txn.fee_included)
        self.assertEqual(txn.fee, 50)
        self.assertEqual(txn.to_amount, 50_000)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 149_950)
        self.assertEqual(self.repo.get_account(self.bank).balance, 50_000)

    def test_fee_can_be_waived(self) -> None:
        txn_id = self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=200_000,
            account_id=self.alipay,
            to_account_id=self.bank,
            fee_waived=True,
        )
        txn = self.repo.get_transaction(txn_id)
        self.assertTrue(txn.fee_waived)
        self.assertEqual(txn.fee, 0)
        self.assertFalse(txn.fee_included)
        self.assertEqual(txn.to_amount, 200_000)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 0)
        self.assertEqual(self.repo.get_account(self.bank).balance, 200_000)

    def test_partial_withdrawal_cannot_overdraw_the_fee(self) -> None:
        with self.assertRaisesRegex(ValueError, "不足以支付手续费"):
            self._transfer(self.alipay, 199_990)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 200_000)
        self.assertEqual(self.repo.get_account(self.bank).balance, 0)

    def test_alipay_minimum_is_ten_cents(self) -> None:
        txn_id = self._transfer(self.alipay, 100)
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.fee, 10)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 199_890)

    def test_incoming_and_non_wallet_transfers_are_free(self) -> None:
        incoming = self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=50_000,
            account_id=self.bank,
            to_account_id=self.alipay,
        )
        self.assertEqual(self.repo.get_transaction(incoming).fee, 0)
        other = self.repo.add_account("另一张卡", "debit", 0)
        outgoing = self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=50_000,
            account_id=self.bank,
            to_account_id=other,
        )
        self.assertEqual(self.repo.get_transaction(outgoing).fee, 0)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 250_000)

    def test_editing_recalculates_and_removing_clears_fee(self) -> None:
        txn_id = self._transfer(self.alipay, 100_000)
        self.repo.update_transaction(
            txn_id,
            date="2026-10-29",
            kind="transfer",
            amount=50_000,
            account_id=self.alipay,
            to_account_id=self.bank,
        )
        self.assertEqual(self.repo.get_transaction(txn_id).fee, 50)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 149_950)
        self.repo.update_transaction(
            txn_id,
            date="2026-10-29",
            kind="transfer",
            amount=50_000,
            account_id=self.bank,
            to_account_id=self.alipay,
        )
        self.assertEqual(self.repo.get_transaction(txn_id).fee, 0)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 250_000)
        self.repo.delete_transaction(txn_id)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 200_000)

    def test_fee_is_counted_as_expense_and_category(self) -> None:
        self._transfer(self.alipay, 100_000)
        stats = self.repo.month_stats("2026-10")
        self.assertEqual(stats.income, 0)
        self.assertEqual(stats.expense, 100)
        breakdown = self.repo.category_breakdown("2026-10", "expense")
        fee_row = next(item for item in breakdown if item.name == "提现手续费")
        self.assertEqual(fee_row.amount, 100)
        self.assertEqual(self.repo.top_payees("2026-10")[0].payee, "提现手续费")
        trend = self.repo.trend(1, "2026-10")
        self.assertEqual(trend[-1].expense, 100)

    def test_foreign_transfer_fee_uses_converted_account_amount(self) -> None:
        self.repo.rates.save(
            RateSnapshot(date="2026-10-29", rates={"USD": 0.15})
        )
        usd = self.repo.add_account("美元卡", "debit", 0, currency="USD")
        txn_id = self.repo.add_transaction(
            date="2026-10-29",
            kind="transfer",
            amount=1_000,
            currency="USD",
            account_id=self.alipay,
            to_account_id=usd,
        )
        txn = self.repo.get_transaction(txn_id)
        self.assertEqual(txn.account_amount, 6_667)
        self.assertEqual(txn.fee, 10)
        self.assertEqual(self.repo.get_account(self.alipay).balance, 193_323)
        self.assertEqual(self.repo.get_account(usd).balance, 1_000)


if __name__ == "__main__":
    unittest.main()
