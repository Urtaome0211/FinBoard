"""Withdrawal-fee rules for the built-in e-wallet accounts.

The rules are intentionally small and local: fees are calculated in CNY
cents, never with binary floating point.  They are only applied when the
source account is an Alipay/WeChat wallet and the transfer leaves that
account.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

#: Names that identify the two wallets.  Both the short and the full name
#: are accepted so an account called "支付宝" also benefits from the rule.
WALLET_ALIASES: dict[str, str] = {
    "支付宝钱包": "支付宝钱包",
    "支付宝": "支付宝钱包",
    "微信钱包": "微信钱包",
    "微信": "微信钱包",
}


@dataclass(frozen=True)
class WithdrawalRule:
    name: str
    label: str
    rate: Decimal
    minimum_fee: int  # cents

    def calculate(self, amount_cents: int) -> int:
        if amount_cents <= 0:
            return 0
        raw = (Decimal(int(amount_cents)) * self.rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return max(self.minimum_fee, int(raw))


ALIPAY_RULE = WithdrawalRule(
    name="支付宝钱包",
    label="支付宝提现",
    rate=Decimal("0.001"),
    minimum_fee=10,
)
WECHAT_RULE = WithdrawalRule(
    name="微信钱包",
    label="微信提现",
    rate=Decimal("0.001"),
    minimum_fee=1,
)
WALLET_RULES: dict[str, WithdrawalRule] = {
    "支付宝钱包": ALIPAY_RULE,
    "微信钱包": WECHAT_RULE,
}


def normalize_account_name(name: str) -> str:
    return " ".join(str(name or "").split())


def withdrawal_rule(account_name: str, currency: str = "CNY") -> WithdrawalRule | None:
    """Return the rule for a source account, or ``None`` if no fee applies.

    The announced rules are in CNY; a wallet denominated in another currency
    is left alone instead of applying a yuan minimum to a foreign amount.
    """
    if (currency or "CNY").upper() != "CNY":
        return None
    normalized = normalize_account_name(account_name)
    return WALLET_RULES.get(WALLET_ALIASES.get(normalized, normalized))


def calculate_withdrawal_fee(
    account_name: str, amount_cents: int, currency: str = "CNY"
) -> int:
    rule = withdrawal_rule(account_name, currency)
    return rule.calculate(amount_cents) if rule else 0
