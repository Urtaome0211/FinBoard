"""Repository layer: every SQL statement lives here.

The repository speaks in integer cents and ISO date strings; it never imports
Qt.  That keeps the financial logic unit-testable without a display server.
"""

from __future__ import annotations

from dataclasses import replace

import calendar
import json
import sqlite3
from datetime import date as date_cls
from datetime import timedelta
from typing import Iterable, Sequence

from .database import Database
from .dates import (
    add_months,
    days_in_month,
    month_bounds,
    month_of,
    normalize_day,
    now_iso,
    parse_month,
    recent_months,
    shift_month,
    today,
    today_iso,
)
from .fees import calculate_withdrawal_fee
from .models import (
    ACCOUNT_TYPES,
    ACCOUNT_TYPE_META,
    Account,
    AccountValuation,
    Attachment,
    BudgetLine,
    Category,
    CategoryRule,
    CategorySpend,
    CsvRule,
    FALLBACK_CATEGORY,
    FIXED_ASSET_TYPE_META,
    Debt,
    DebtPayment,
    FixedAsset,
    FixedAssetValuation,
    ForecastPoint,
    Holding,
    HoldingsSummary,
    InvestmentDisposal,
    InvestmentLot,
    InvestmentTrade,
    KIND_LABELS,
    MonthStats,
    RangeReport,
    NetWorth,
    NetWorthPoint,
    PayeeSpend,
    PlannedTransaction,
    Receivable,
    Reconciliation,
    RecurringTransaction,
    SavingsGoal,
    Tag,
    TermDeposit,
    Transaction,
    TransactionBalance,
    TransactionFilter,
    TransactionSplit,
    TransactionTemplate,
)
from .insights import FixedCost, detect_fixed_costs
from .investing import xirr
from .loans import (
    CreditCycle,
    Installment,
    PayoffItem,
    PayoffPlan,
    amortization,
    credit_cycle,
    payoff_plan,
)
from .money import CURRENCIES, MAX_AMOUNT_CENTS, MAX_QUANTITY_UNITS
from .rates import RateError, RateStore

_TXN_SELECT = """
SELECT t.id, t.date, t.kind, t.amount, t.currency, t.account_amount, t.to_amount, t.fee,
       t.fee_waived, t.fee_included, t.recurring_id, t.refund_of_id, t.import_hash,
       t.category_id, c.name AS category_name, c.color AS category_color,
       t.account_id, a.name AS account_name, a.currency AS account_currency,
       t.to_account_id, ta.name AS to_account_name,
       ta.currency AS to_account_currency,
       t.payee, t.note, t.created_at
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN accounts ta ON ta.id = t.to_account_id
LEFT JOIN categories c ON c.id = t.category_id
"""

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")


def next_recurring_date(day: str, frequency: str, interval: int = 1) -> str:
    """Advance an ISO date by one recurrence interval, clamping month ends."""
    current = date_cls.fromisoformat(day)
    interval = max(1, int(interval))
    if frequency == "daily":
        return (current + timedelta(days=interval)).isoformat()
    if frequency == "weekly":
        return (current + timedelta(weeks=interval)).isoformat()
    if frequency == "monthly":
        month_index = current.year * 12 + (current.month - 1) + interval
        year, month0 = divmod(month_index, 12)
        month = month0 + 1
        day_number = min(current.day, calendar.monthrange(year, month)[1])
        return date_cls(year, month, day_number).isoformat()
    if frequency == "yearly":
        year = current.year + interval
        day_number = min(current.day, calendar.monthrange(year, current.month)[1])
        return date_cls(year, current.month, day_number).isoformat()
    raise ValueError("不支持的重复频率")


_RECURRING_SELECT = """
SELECT r.id, r.name, r.kind, r.amount, r.currency, r.account_id,
       a.name AS account_name, r.category_id, c.name AS category_name,
       r.to_account_id, ta.name AS to_account_name, r.payee, r.note,
       r.fee_waived, r.frequency, r.interval_count, r.start_date, r.end_date,
       r.next_date, r.active, r.created_at
FROM recurring_transactions r
JOIN accounts a ON a.id = r.account_id
LEFT JOIN accounts ta ON ta.id = r.to_account_id
LEFT JOIN categories c ON c.id = r.category_id
"""


class Repository:
    def __init__(
        self,
        db: Database,
        *,
        base_currency: str = "CNY",
        rates: RateStore | None = None,
    ) -> None:
        self.db = db
        self._base_currency = base_currency if base_currency in CURRENCIES else "CNY"
        self.rates = rates or RateStore(db)

    @property
    def base_currency(self) -> str:
        return self._base_currency

    def set_base_currency(self, code: str) -> None:
        if code not in CURRENCIES:
            raise ValueError("不支持的币种")
        self._base_currency = code

    # ---------------------------------------------------------------- helpers
    @property
    def conn(self) -> sqlite3.Connection:
        return self.db.conn

    @staticmethod
    def _clean_name(value: str, label: str, limit: int = 40) -> str:
        name = " ".join(str(value or "").split())
        if not name:
            raise ValueError(f"{label}不能为空")
        if len(name) > limit:
            raise ValueError(f"{label}不能超过 {limit} 个字符")
        return name

    @staticmethod
    def _category(row: sqlite3.Row) -> Category:
        return Category(
            id=int(row["id"]), name=row["name"], kind=row["kind"], color=row["color"]
        )

    @staticmethod
    def _account(row: sqlite3.Row) -> Account:
        return Account(
            id=int(row["id"]),
            name=row["name"],
            type=row["type"],
            opening_balance=int(row["opening_balance"]),
            note=row["note"] or "",
            archived=bool(row["archived"]),
            balance=int(row["balance"]),
            currency=row["currency"] or "CNY",
            last_valuation=(
                int(row["last_valuation"])
                if row["last_valuation"] is not None
                else None
            ),
            last_valuation_date=row["last_valuation_date"] or "",
            valuation_count=int(row["valuation_count"] or 0),
            adjustment=int(row["adjustment"] or 0),
            holdings_value=int(row["holdings_value"] or 0),
            is_system=bool(row["is_system"]) if "is_system" in row.keys() else False,
        )

    @staticmethod
    def _transaction(row: sqlite3.Row) -> Transaction:
        return Transaction(
            id=int(row["id"]),
            date=row["date"],
            kind=row["kind"],
            amount=int(row["amount"]),
            account_id=int(row["account_id"]),
            account_name=row["account_name"],
            category_id=int(row["category_id"]) if row["category_id"] is not None else None,
            category_name=row["category_name"] or "",
            category_color=row["category_color"] or "",
            to_account_id=int(row["to_account_id"]) if row["to_account_id"] is not None else None,
            to_account_name=row["to_account_name"] or "",
            payee=row["payee"] or "",
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            currency=row["currency"] or "CNY",
            account_amount=int(row["account_amount"] or row["amount"]),
            to_amount=int(row["to_amount"] or 0),
            fee=int(row["fee"] or 0),
            fee_waived=bool(row["fee_waived"]),
            fee_included=bool(row["fee_included"]),
            recurring_id=(
                int(row["recurring_id"]) if row["recurring_id"] is not None else None
            ),
            refund_of_id=(
                int(row["refund_of_id"]) if row["refund_of_id"] is not None else None
            ),
            account_currency=row["account_currency"] or "CNY",
            to_account_currency=row["to_account_currency"] or "CNY",
            import_hash=row["import_hash"] or "",
        )

    @staticmethod
    def _recurring(row: sqlite3.Row) -> RecurringTransaction:
        return RecurringTransaction(
            id=int(row["id"]),
            name=row["name"],
            kind=row["kind"],
            amount=int(row["amount"]),
            account_id=int(row["account_id"]),
            account_name=row["account_name"] or "",
            category_id=(
                int(row["category_id"]) if row["category_id"] is not None else None
            ),
            category_name=row["category_name"] or "",
            to_account_id=(
                int(row["to_account_id"])
                if row["to_account_id"] is not None
                else None
            ),
            to_account_name=row["to_account_name"] or "",
            payee=row["payee"] or "",
            note=row["note"] or "",
            fee_waived=bool(row["fee_waived"]),
            frequency=row["frequency"],
            interval_count=int(row["interval_count"]),
            start_date=row["start_date"],
            end_date=row["end_date"],
            next_date=row["next_date"],
            active=bool(row["active"]),
            currency=row["currency"] or "CNY",
            created_at=row["created_at"] or "",
        )

    # --------------------------------------------------------------- accounts
    def accounts(self, *, include_archived: bool = False) -> list[Account]:
        where = "" if include_archived else "WHERE a.archived = 0"
        rows = self.conn.execute(
            f"""
            SELECT a.id, a.name, a.type, a.opening_balance, a.note, a.archived,
                   a.currency, a.adjustment, a.is_system,
                   vc.valuation_count AS valuation_count,
                   lv.value AS last_valuation,
                   lv.date AS last_valuation_date,
                   COALESCE(hv.market, 0) AS holdings_value,
                   CASE
                       WHEN a.type = 'investment' AND lv.value IS NOT NULL
                       THEN lv.value + a.adjustment + COALESCE(SUM(CASE
                           WHEN t.date > lv.date
                                AND t.kind = 'income'   AND t.account_id    = a.id
                                THEN  t.account_amount
                           WHEN t.date > lv.date
                                AND t.kind = 'expense'  AND t.account_id    = a.id
                                THEN -t.account_amount
                           WHEN t.date > lv.date
                                AND t.kind = 'transfer' AND t.account_id    = a.id
                                THEN -(t.account_amount + CASE
                                    WHEN t.fee_included = 0 THEN COALESCE(t.fee, 0)
                                    ELSE 0 END)
                           WHEN t.date > lv.date
                                AND t.kind = 'transfer' AND t.to_account_id = a.id
                                THEN  t.to_amount
                           ELSE 0 END), 0)
                       ELSE a.opening_balance + a.adjustment + COALESCE(SUM(CASE
                           WHEN t.kind = 'income'   AND t.account_id    = a.id THEN  t.account_amount
                           WHEN t.kind = 'expense'  AND t.account_id    = a.id THEN -t.account_amount
                           WHEN t.kind = 'transfer' AND t.account_id    = a.id
                                THEN -(t.account_amount + CASE
                                    WHEN t.fee_included = 0 THEN COALESCE(t.fee, 0)
                                    ELSE 0 END)
                           WHEN t.kind = 'transfer' AND t.to_account_id = a.id THEN  t.to_amount
                           ELSE 0 END), 0)
                           + CASE WHEN a.type = 'investment' THEN COALESCE(hv.market, 0) ELSE 0 END
                   END AS balance
            FROM accounts a
            LEFT JOIN transactions t
                   ON t.account_id = a.id OR t.to_account_id = a.id
            LEFT JOIN (
                SELECT account_id,
                       SUM((quantity_units * price + 500000) / 1000000) AS market
                FROM holdings
                GROUP BY account_id
            ) hv ON hv.account_id = a.id
            LEFT JOIN (
                SELECT account_id, COUNT(*) AS valuation_count, MAX(date) AS latest_date
                FROM account_valuations
                GROUP BY account_id
            ) vc ON vc.account_id = a.id
            LEFT JOIN account_valuations lv
                   ON lv.account_id = a.id AND lv.date = vc.latest_date
            {where}
            GROUP BY a.id
            ORDER BY a.archived, a.id
            """
        ).fetchall()
        return [self._account(row) for row in rows]

    def account_balance(self, account_id: int) -> int:
        for account in self.accounts(include_archived=True):
            if account.id == account_id:
                return account.balance
        raise ValueError("账户不存在")

    def account_balance_at(self, account_id: int, cutoff: str) -> int:
        """Signed account balance at the end of ``cutoff`` (ISO day).

        Investment accounts use their latest valuation on or before the day;
        other accounts replay every transaction up to the day.
        """
        day = normalize_day(cutoff)
        account = self.get_account(account_id, include_archived=True)
        valuation = None
        if account.type == "investment":
            valuation = self.conn.execute(
                "SELECT date, value FROM account_valuations"
                " WHERE account_id = ? AND date <= ?"
                " ORDER BY date DESC LIMIT 1",
                (account_id, day),
            ).fetchone()

        flow_sql = """
            SELECT COALESCE(SUM(CASE
                WHEN t.kind = 'income'   AND t.account_id    = ? THEN  t.account_amount
                WHEN t.kind = 'expense'  AND t.account_id    = ? THEN -t.account_amount
                WHEN t.kind = 'transfer' AND t.account_id    = ?2
                     THEN -(t.account_amount + CASE WHEN t.fee_included = 0
                              THEN COALESCE(t.fee, 0) ELSE 0 END)
                WHEN t.kind = 'transfer' AND t.to_account_id = ?2 THEN t.to_amount
                ELSE 0 END), 0)
            FROM transactions t
            WHERE (t.account_id = ?2 OR t.to_account_id = ?2)
        """
        params: list[object] = [account_id, account_id]
        if valuation is not None:
            flow_sql += " AND t.date > ?"
            params.append(valuation["date"])
        flow_sql += " AND t.date <= ?"
        params.append(day)
        flows = int(self.conn.execute(flow_sql, tuple(params)).fetchone()[0])

        if valuation is not None:
            balance = (
                int(valuation["value"]) + account.adjustment + flows
            )
        else:
            balance = account.opening_balance + account.adjustment + flows
            if account.type == "investment":
                market = self.conn.execute(
                    "SELECT COALESCE(SUM((quantity_units * price + 500000) / 1000000), 0)"
                    " FROM holdings WHERE account_id = ?",
                    (account_id,),
                ).fetchone()[0]
                balance += int(market)
        return balance

    def withdrawal_fee(self, account_id: int, account_amount: int) -> int:
        """Fee charged when this account sends money out, in account cents."""
        account = self.get_account(account_id, include_archived=True)
        return calculate_withdrawal_fee(
            account.name, int(account_amount), account.currency
        )

    def _available_before(
        self, account_id: int, exclude_transaction_id: int | None = None
    ) -> int:
        """Cash available to a new transfer, excluding an edited row."""
        balance = self.get_account(account_id, include_archived=True).cash_balance
        if exclude_transaction_id is None:
            return balance
        old = self.get_transaction(exclude_transaction_id)
        if old.account_id == account_id:
            if old.kind == "transfer":
                balance += old.account_amount + (
                    0 if old.fee_included else old.fee
                )
            elif old.kind == "expense":
                balance += old.account_amount
            elif old.kind == "income":
                balance -= old.account_amount
        if old.kind == "transfer" and old.to_account_id == account_id:
            balance -= old.to_amount
        return balance

    def available_balance(
        self, account_id: int, exclude_transaction_id: int | None = None
    ) -> int:
        """Public wrapper used by the transaction dialog preview."""
        return self._available_before(account_id, exclude_transaction_id)

    # ------------------------------------------------------------------ debts
    @staticmethod
    def _debt(row: sqlite3.Row, account: Account) -> Debt:
        return Debt(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            kind=row["kind"],
            principal=int(row["principal"]),
            annual_rate_bp=int(row["annual_rate_bp"]),
            term_months=int(row["term_months"]),
            start_date=row["start_date"],
            payment_method=row["payment_method"],
            billing_day=row["billing_day"],
            due_day=row["due_day"],
            credit_limit=int(row["credit_limit"]),
            min_payment_bp=int(row["min_payment_bp"]),
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            account_name=account.name,
            account_balance=account.balance,
            currency=account.currency,
        )

    def debts(self) -> list[Debt]:
        rows = self.conn.execute(
            "SELECT * FROM debts ORDER BY kind, id"
        ).fetchall()
        return [
            self._debt(
                row,
                self.get_account(int(row["account_id"]), include_archived=True),
            )
            for row in rows
        ]

    def get_debt(self, account_id: int) -> Debt | None:
        row = self.conn.execute(
            "SELECT * FROM debts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return None
        return self._debt(
            row, self.get_account(account_id, include_archived=True)
        )

    def save_debt(
        self,
        account_id: int,
        *,
        kind: str,
        principal: int = 0,
        annual_rate_bp: int = 0,
        term_months: int = 0,
        start_date: str | None = None,
        payment_method: str = "equal_payment",
        billing_day: int | None = None,
        due_day: int | None = None,
        credit_limit: int = 0,
        min_payment_bp: int = 1000,
        note: str = "",
    ) -> int:
        account = self.get_account(account_id, include_archived=True)
        if account.type not in ("loan", "credit"):
            raise ValueError("只有贷款或信用卡账户可以设置负债计划")
        expected = "loan" if account.type == "loan" else "credit"
        if kind != expected:
            raise ValueError("负债类型与账户类型不一致")
        principal = int(principal)
        annual_rate_bp = int(annual_rate_bp)
        term_months = int(term_months)
        credit_limit = int(credit_limit)
        min_payment_bp = int(min_payment_bp)
        if not 0 <= principal <= MAX_AMOUNT_CENTS:
            raise ValueError("本金金额无效")
        if not 0 <= annual_rate_bp <= 10000:
            raise ValueError("年利率应在 0% 到 100% 之间")
        if kind == "loan":
            if term_months <= 0 or term_months > 720:
                raise ValueError("贷款期限必须在 1 到 720 个月之间")
            if payment_method not in ("equal_payment", "equal_principal"):
                raise ValueError("不支持的还款方式")
        else:
            term_months = 0
            if not 1 <= int(billing_day or 0) <= 28:
                raise ValueError("账单日必须在 1 到 28 日之间")
            if not 1 <= int(due_day or 0) <= 28:
                raise ValueError("还款日必须在 1 到 28 日之间")
        if not 0 <= credit_limit <= MAX_AMOUNT_CENTS:
            raise ValueError("信用额度无效")
        if not 0 <= min_payment_bp <= 10000:
            raise ValueError("最低还款比例无效")
        start = normalize_day(start_date) if start_date else today_iso()
        note = str(note or "").strip()[:200]
        stamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO debts
                (account_id, kind, principal, annual_rate_bp, term_months,
                 start_date, payment_method, billing_day, due_day, credit_limit,
                 min_payment_bp, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                kind=excluded.kind,
                principal=excluded.principal,
                annual_rate_bp=excluded.annual_rate_bp,
                term_months=excluded.term_months,
                start_date=excluded.start_date,
                payment_method=excluded.payment_method,
                billing_day=excluded.billing_day,
                due_day=excluded.due_day,
                credit_limit=excluded.credit_limit,
                min_payment_bp=excluded.min_payment_bp,
                note=excluded.note,
                updated_at=excluded.updated_at
            """,
            (
                account_id,
                kind,
                principal,
                annual_rate_bp,
                term_months,
                start,
                payment_method,
                int(billing_day) if billing_day is not None else None,
                int(due_day) if due_day is not None else None,
                credit_limit,
                min_payment_bp,
                note,
                stamp,
                stamp,
            ),
        )
        self.conn.commit()
        return account_id

    def delete_debt(self, account_id: int) -> None:
        self.conn.execute("DELETE FROM debts WHERE account_id = ?", (account_id,))
        self.conn.commit()

    def debt_schedule(self, account_id: int) -> list[Installment]:
        debt = self.get_debt(account_id)
        if debt is None or not debt.is_loan or debt.principal <= 0:
            return []
        start = debt.start_date or today_iso()
        if debt.outstanding <= 0:
            return []
        if debt.outstanding < debt.principal:
            try:
                first = date_cls.fromisoformat(start)
                current = date_cls.fromisoformat(today_iso())
                elapsed = max(
                    0, (current.year - first.year) * 12 + current.month - first.month
                )
            except ValueError:
                elapsed = 0
            remaining = max(1, debt.term_months - elapsed)
            return amortization(
                debt.outstanding,
                debt.annual_rate_bp,
                remaining,
                today_iso(),
                debt.payment_method,
            )
        return amortization(
            debt.principal,
            debt.annual_rate_bp,
            debt.term_months,
            start,
            debt.payment_method,
        )

    def debt_credit_cycle(self, account_id: int) -> CreditCycle | None:
        debt = self.get_debt(account_id)
        if debt is None or not debt.is_credit:
            return None
        return credit_cycle(
            int(debt.billing_day or 1), int(debt.due_day or 1), today_iso()
        )

    def _loan_next_payment(self, debt: Debt) -> int:
        schedule = self.debt_schedule(debt.account_id)
        if not schedule:
            return max(0, debt.outstanding)
        current = today_iso()
        for row in schedule:
            if row.date >= current:
                return row.payment
        return max(0, debt.outstanding)

    def debt_payoff_plan(
        self, *, extra_monthly: int = 0, method: str = "avalanche"
    ) -> PayoffPlan:
        items: list[PayoffItem] = []
        for debt in self.debts():
            if debt.outstanding <= 0:
                continue
            minimum = (
                debt.min_payment
                if debt.is_credit
                else self._loan_next_payment(debt)
            )
            if minimum <= 0:
                minimum = debt.outstanding
            items.append(
                PayoffItem(
                    name=debt.account_name,
                    balance=debt.outstanding,
                    annual_rate_bp=debt.annual_rate_bp,
                    min_payment=minimum,
                )
            )
        if not items:
            return PayoffPlan(months=0, total_interest=0, order=(), rows=())
        return payoff_plan(
            items, extra_monthly=int(extra_monthly), method=method
        )

    @staticmethod
    def _debt_payment_split(debt: Debt, amount: int) -> tuple[int, int]:
        """Split a repayment into principal and interest in cents."""
        amount = int(amount)
        if amount <= 0:
            raise ValueError("还款金额必须大于 0")
        outstanding = max(0, debt.outstanding)
        if outstanding <= 0:
            raise ValueError("这笔负债已经还清")
        if debt.is_credit:
            if amount > outstanding:
                raise ValueError("还款金额不能超过剩余欠款")
            return amount, 0
        monthly_interest = (
            outstanding * debt.annual_rate_bp + 60_000
        ) // 120_000
        if amount <= monthly_interest:
            return 0, amount
        principal = amount - monthly_interest
        if principal > outstanding:
            principal = outstanding
            interest = amount - principal
            if interest > monthly_interest:
                raise ValueError("还款金额超过剩余本金与本期利息")
            return principal, interest
        return principal, monthly_interest

    def debt_payment_preview(self, account_id: int, amount: int) -> dict[str, int]:
        debt = self.get_debt(account_id)
        if debt is None:
            raise ValueError("请先设置负债信息")
        principal, interest = self._debt_payment_split(debt, amount)
        return {
            "amount": int(amount),
            "principal": principal,
            "interest": interest,
            "outstanding": debt.outstanding,
            "monthly_interest": (
                (debt.outstanding * debt.annual_rate_bp + 60_000) // 120_000
                if debt.is_loan
                else 0
            ),
        }

    def record_debt_payment(
        self,
        account_id: int,
        *,
        amount: int,
        source_account_id: int,
        paid_on: str | None = None,
        note: str = "",
    ) -> dict[str, object]:
        """Record a repayment, creating the principal transfer and interest expense."""
        debt = self.get_debt(account_id)
        if debt is None:
            raise ValueError("请先设置负债信息")
        account = self.get_account(account_id, include_archived=True)
        source = self.get_account(source_account_id, include_archived=True)
        if source.type not in ("cash", "debit", "investment"):
            raise ValueError("还款来源必须是现金、储蓄或投资账户")
        if source.id == account.id:
            raise ValueError("还款来源不能是负债账户本身")
        if source.archived:
            raise ValueError("还款来源账户已归档")
        if source.currency != account.currency:
            raise ValueError("还款来源与负债账户币种不一致")
        principal, interest = self._debt_payment_split(debt, amount)
        if source.cash_balance < int(amount):
            raise ValueError("还款来源账户余额不足")
        day = normalize_day(paid_on) if paid_on else today_iso()
        text = str(note or "").strip()[:200]
        transfer_id = None
        interest_id = None
        if principal > 0:
            transfer_id = self.add_transaction(
                date=day,
                kind="transfer",
                amount=principal,
                account_id=source.id,
                to_account_id=account.id,
                payee=account.name,
                note=text or "负债还款",
                currency=source.currency,
                account_amount=principal,
                to_amount=principal,
                fee_waived=True,
                fee_included=True,
            )
        if interest > 0:
            category = self.conn.execute(
                "SELECT id FROM categories WHERE kind = 'expense' AND name = '利息支出'"
            ).fetchone()
            if category is None:
                cursor = self.conn.execute(
                    "INSERT INTO categories (name, kind, color, created_at)"
                    " VALUES ('利息支出', 'expense', '#E5484D', ?)",
                    (now_iso(),),
                )
                category_id = int(cursor.lastrowid)
            else:
                category_id = int(category["id"])
            interest_id = self.add_transaction(
                date=day,
                kind="expense",
                amount=interest,
                account_id=source.id,
                category_id=category_id,
                payee=account.name,
                note=text or "负债利息",
                currency=source.currency,
            )
        cursor = self.conn.execute(
            "INSERT INTO debt_payments"
            " (account_id, paid_on, amount, principal, interest, transfer_id,"
            "  interest_transaction_id, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                account_id,
                day,
                int(amount),
                principal,
                interest,
                transfer_id,
                interest_id,
                text,
                now_iso(),
            ),
        )
        self.conn.commit()
        latest = self.get_debt(account_id)
        return {
            "id": int(cursor.lastrowid),
            "account_id": account_id,
            "paid_on": day,
            "amount": int(amount),
            "principal": principal,
            "interest": interest,
            "transfer_id": transfer_id,
            "interest_transaction_id": interest_id,
            "outstanding_after": latest.outstanding if latest else 0,
        }

    def _debt_payment(self, row: sqlite3.Row) -> DebtPayment:
        return DebtPayment(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            paid_on=row["paid_on"],
            amount=int(row["amount"]),
            principal=int(row["principal"]),
            interest=int(row["interest"]),
            transfer_id=row["transfer_id"],
            interest_transaction_id=row["interest_transaction_id"],
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            account_name=row["account_name"] or "",
            currency=row["currency"] or "CNY",
        )

    def debt_payments(self, account_id: int | None = None) -> list[DebtPayment]:
        if account_id is None:
            rows = self.conn.execute(
                "SELECT p.*, a.name AS account_name, a.currency AS currency"
                " FROM debt_payments p JOIN accounts a ON a.id = p.account_id"
                " ORDER BY p.paid_on DESC, p.id DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT p.*, a.name AS account_name, a.currency AS currency"
                " FROM debt_payments p JOIN accounts a ON a.id = p.account_id"
                " WHERE p.account_id = ? ORDER BY p.paid_on DESC, p.id DESC",
                (account_id,),
            ).fetchall()
        return [self._debt_payment(row) for row in rows]

    def debt_paid_principal(self, account_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(principal), 0) FROM debt_payments WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return int(row[0])

    def debt_paid_interest(self, account_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(interest), 0) FROM debt_payments WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------- planned
    @staticmethod
    def _planned(row: sqlite3.Row) -> PlannedTransaction:
        return PlannedTransaction(
            id=int(row["id"]),
            date=row["date"],
            kind=row["kind"],
            amount=int(row["amount"]),
            currency=row["currency"] or "CNY",
            account_id=int(row["account_id"]),
            account_name=row["account_name"] or "",
            category_id=row["category_id"],
            category_name=row["category_name"] or "",
            to_account_id=row["to_account_id"],
            to_account_name=row["to_account_name"] or "",
            payee=row["payee"] or "",
            note=row["note"] or "",
            status=row["status"],
            transaction_id=row["transaction_id"],
            created_at=row["created_at"] or "",
        )

    def planned_transactions(
        self, *, status: str | None = None
    ) -> list[PlannedTransaction]:
        sql = """
            SELECT p.*, a.name AS account_name, ta.name AS to_account_name,
                   c.name AS category_name
            FROM planned_transactions p
            JOIN accounts a ON a.id = p.account_id
            LEFT JOIN accounts ta ON ta.id = p.to_account_id
            LEFT JOIN categories c ON c.id = p.category_id
        """
        params: tuple[object, ...] = ()
        if status is not None:
            sql += " WHERE p.status = ?"
            params = (status,)
        sql += " ORDER BY p.date, p.id"
        return [self._planned(row) for row in self.conn.execute(sql, params)]

    def get_planned_transaction(self, planned_id: int) -> PlannedTransaction:
        for item in self.planned_transactions():
            if item.id == planned_id:
                return item
        raise ValueError("计划交易不存在")

    def add_planned_transaction(
        self,
        date: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        currency: str = "CNY",
    ) -> int:
        self._validate_txn(
            kind=kind,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            currency=currency,
        )
        cursor = self.conn.execute(
            "INSERT INTO planned_transactions"
            " (date, kind, amount, currency, account_id, category_id,"
            "  to_account_id, payee, note, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)",
            (
                normalize_day(date),
                kind,
                int(amount),
                currency,
                account_id,
                category_id,
                to_account_id,
                str(payee or "").strip()[:80],
                str(note or "").strip()[:200],
                now_iso(),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_planned_transaction(
        self,
        planned_id: int,
        *,
        date: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        currency: str = "CNY",
    ) -> None:
        item = self.get_planned_transaction(planned_id)
        if item.status != "planned":
            raise ValueError("已完成的计划不能修改")
        self._validate_txn(
            kind=kind,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            currency=currency,
        )
        self.conn.execute(
            "UPDATE planned_transactions SET date=?, kind=?, amount=?, currency=?,"
            " account_id=?, category_id=?, to_account_id=?, payee=?, note=?,"
            " updated_at=? WHERE id=?",
            (
                normalize_day(date),
                kind,
                int(amount),
                currency,
                account_id,
                category_id,
                to_account_id,
                str(payee or "").strip()[:80],
                str(note or "").strip()[:200],
                now_iso(),
                planned_id,
            ),
        )
        self.conn.commit()

    def confirm_planned_transaction(self, planned_id: int) -> int:
        item = self.get_planned_transaction(planned_id)
        if item.status != "planned":
            raise ValueError("计划交易已经处理过了")
        transaction_id = self.add_transaction(
            date=item.date,
            kind=item.kind,
            amount=item.amount,
            account_id=item.account_id,
            category_id=item.category_id,
            to_account_id=item.to_account_id,
            payee=item.payee,
            note=item.note,
            currency=item.currency,
        )
        self.conn.execute(
            "UPDATE planned_transactions SET status='done', transaction_id=?,"
            " updated_at=? WHERE id=?",
            (transaction_id, now_iso(), planned_id),
        )
        self.conn.commit()
        return transaction_id

    def cancel_planned_transaction(self, planned_id: int) -> None:
        item = self.get_planned_transaction(planned_id)
        if item.status != "planned":
            raise ValueError("计划交易已经处理过了")
        self.conn.execute(
            "UPDATE planned_transactions SET status='cancelled', updated_at=?"
            " WHERE id=?",
            (now_iso(), planned_id),
        )
        self.conn.commit()

    def delete_planned_transaction(self, planned_id: int) -> None:
        self.conn.execute(
            "DELETE FROM planned_transactions WHERE id = ?", (planned_id,)
        )
        self.conn.commit()

    # ---------------------------------------------------------- receivables
    @staticmethod
    def _receivable(row: sqlite3.Row) -> Receivable:
        return Receivable(
            id=int(row["id"]),
            direction=row["direction"],
            counterparty=row["counterparty"],
            amount=int(row["amount"]),
            currency=row["currency"] or "CNY",
            date=row["date"],
            due_date=row["due_date"],
            account_id=row["account_id"],
            account_name=row["account_name"] or "",
            note=row["note"] or "",
            status=row["status"],
            settled_at=row["settled_at"],
            created_at=row["created_at"] or "",
        )

    def receivables(self, *, status: str | None = None) -> list[Receivable]:
        sql = """
            SELECT r.*, a.name AS account_name
            FROM receivables r
            LEFT JOIN accounts a ON a.id = r.account_id
        """
        params: tuple[object, ...] = ()
        if status is not None:
            sql += " WHERE r.status = ?"
            params = (status,)
        sql += " ORDER BY r.status, r.due_date, r.id"
        return [self._receivable(row) for row in self.conn.execute(sql, params)]

    def receivables_totals(self) -> dict[str, int]:
        receivable = 0
        payable = 0
        for item in self.receivables(status="open"):
            value = self._to_base(item.amount, item.currency, item.date)
            if item.direction == "receivable":
                receivable += value
            else:
                payable += value
        return {"receivable": receivable, "payable": payable}

    def add_receivable(
        self,
        *,
        direction: str,
        counterparty: str,
        amount: int,
        currency: str = "CNY",
        date: str | None = None,
        due_date: str | None = None,
        account_id: int | None = None,
        note: str = "",
    ) -> int:
        if direction not in ("receivable", "payable"):
            raise ValueError("往来款方向无效")
        counterparty = self._clean_name(counterparty, "对方名称", 60)
        amount = int(amount)
        if amount <= 0 or amount > MAX_AMOUNT_CENTS:
            raise ValueError("往来款金额必须大于 0")
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        day = normalize_day(date) if date else today_iso()
        due = normalize_day(due_date) if due_date else None
        if due and due < day:
            raise ValueError("到期日不能早于发生日")
        if account_id is not None:
            self.get_account(int(account_id))
        cursor = self.conn.execute(
            "INSERT INTO receivables"
            " (direction, counterparty, amount, currency, date, due_date,"
            "  account_id, note, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (
                direction,
                counterparty,
                amount,
                currency,
                day,
                due,
                account_id,
                str(note or "").strip()[:200],
                now_iso(),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def settle_receivable(self, receivable_id: int) -> None:
        self.conn.execute(
            "UPDATE receivables SET status='settled', settled_at=?, updated_at=?"
            " WHERE id=? AND status='open'",
            (today_iso(), now_iso(), receivable_id),
        )
        self.conn.commit()

    def reopen_receivable(self, receivable_id: int) -> None:
        self.conn.execute(
            "UPDATE receivables SET status='open', settled_at=NULL, updated_at=?"
            " WHERE id=?",
            (now_iso(), receivable_id),
        )
        self.conn.commit()

    def delete_receivable(self, receivable_id: int) -> None:
        self.conn.execute(
            "DELETE FROM receivables WHERE id = ?", (receivable_id,)
        )
        self.conn.commit()

    # ------------------------------------------------------------- recurring
    def _clean_recurring(
        self,
        *,
        name: str,
        kind: str,
        amount: int,
        currency: str,
        account_id: int,
        category_id: int | None,
        to_account_id: int | None,
        frequency: str,
        interval_count: int,
        start_date: str,
        end_date: str | None,
    ) -> tuple[str, str, str | None]:
        name = self._clean_name(name, "名称", 60)
        if frequency not in FREQUENCIES:
            raise ValueError("重复频率无效")
        try:
            interval_count = int(interval_count)
        except (TypeError, ValueError):
            raise ValueError("重复间隔无效") from None
        if not 1 <= interval_count <= 365:
            raise ValueError("重复间隔必须在 1 到 365 之间")
        start = normalize_day(start_date)
        end = normalize_day(end_date) if end_date else None
        if end and end < start:
            raise ValueError("结束日期不能早于开始日期")
        self._validate_txn(
            kind=kind,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            currency=currency,
        )
        return name, start, end

    def recurring_rules(
        self, *, active_only: bool = False
    ) -> list[RecurringTransaction]:
        where = "WHERE r.active = 1" if active_only else ""
        rows = self.conn.execute(
            f"{_RECURRING_SELECT} {where}"
            " ORDER BY r.active DESC, r.next_date, r.id"
        ).fetchall()
        return [self._recurring(row) for row in rows]

    def due_recurring(self, day: str | None = None) -> list[RecurringTransaction]:
        day = normalize_day(day) if day else today_iso()
        rows = self.conn.execute(
            f"{_RECURRING_SELECT} WHERE r.active = 1 AND r.next_date <= ?"
            " ORDER BY r.next_date, r.id",
            (day,),
        ).fetchall()
        return [self._recurring(row) for row in rows]

    def get_recurring(self, recurring_id: int) -> RecurringTransaction:
        row = self.conn.execute(
            f"{_RECURRING_SELECT} WHERE r.id = ?", (recurring_id,)
        ).fetchone()
        if row is None:
            raise ValueError("定期交易不存在")
        return self._recurring(row)

    def add_recurring(
        self,
        *,
        name: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        fee_waived: bool = False,
        frequency: str = "monthly",
        interval_count: int = 1,
        start_date: str | None = None,
        end_date: str | None = None,
        active: bool = True,
        currency: str = "CNY",
    ) -> int:
        start = normalize_day(start_date) if start_date else today_iso()
        name, start, end = self._clean_recurring(
            name=name,
            kind=kind,
            amount=amount,
            currency=currency,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            frequency=frequency,
            interval_count=interval_count,
            start_date=start,
            end_date=end_date,
        )
        cursor = self.conn.execute(
            "INSERT INTO recurring_transactions"
            " (name, kind, amount, currency, account_id, category_id, to_account_id,"
            "  payee, note, fee_waived, frequency, interval_count, start_date, end_date,"
            "  next_date, active, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                kind,
                int(amount),
                currency,
                account_id,
                category_id,
                to_account_id,
                str(payee or "").strip()[:60],
                str(note or "").strip()[:200],
                int(bool(fee_waived)),
                frequency,
                int(interval_count),
                start,
                end,
                start,
                int(bool(active)),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_recurring(
        self,
        recurring_id: int,
        *,
        name: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        fee_waived: bool = False,
        frequency: str = "monthly",
        interval_count: int = 1,
        start_date: str,
        end_date: str | None = None,
        active: bool = True,
        currency: str = "CNY",
    ) -> None:
        current = self.get_recurring(recurring_id)
        name, start, end = self._clean_recurring(
            name=name,
            kind=kind,
            amount=amount,
            currency=currency,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            frequency=frequency,
            interval_count=interval_count,
            start_date=start_date,
            end_date=end_date,
        )
        next_date = current.next_date
        if start != current.start_date:
            next_date = start
        self.conn.execute(
            "UPDATE recurring_transactions SET name = ?, kind = ?, amount = ?,"
            " currency = ?, account_id = ?, category_id = ?, to_account_id = ?,"
            " payee = ?, note = ?, fee_waived = ?, frequency = ?, interval_count = ?,"
            " start_date = ?, end_date = ?, next_date = ?, active = ?, updated_at = ?"
            " WHERE id = ?",
            (
                name,
                kind,
                int(amount),
                currency,
                account_id,
                category_id,
                to_account_id,
                str(payee or "").strip()[:60],
                str(note or "").strip()[:200],
                int(bool(fee_waived)),
                frequency,
                int(interval_count),
                start,
                end,
                next_date,
                int(bool(active)),
                now_iso(),
                recurring_id,
            ),
        )
        self.conn.commit()

    def set_recurring_active(self, recurring_id: int, active: bool) -> None:
        self.conn.execute(
            "UPDATE recurring_transactions SET active = ?, updated_at = ? WHERE id = ?",
            (int(bool(active)), now_iso(), recurring_id),
        )
        self.conn.commit()

    def delete_recurring(self, recurring_id: int) -> None:
        self.conn.execute(
            "DELETE FROM recurring_transactions WHERE id = ?", (recurring_id,)
        )
        self.conn.commit()

    def post_recurring(self, recurring_id: int) -> int:
        """Post the next occurrence and advance the schedule by one interval."""
        rule = self.get_recurring(recurring_id)
        if not rule.active:
            raise ValueError("该定期交易已停用")
        if rule.next_date > today_iso():
            raise ValueError("该定期交易尚未到期")
        transaction_id = self.add_transaction(
            date=rule.next_date,
            kind=rule.kind,
            amount=rule.amount,
            currency=rule.currency,
            account_id=rule.account_id,
            category_id=rule.category_id,
            to_account_id=rule.to_account_id,
            payee=rule.payee,
            note=rule.note or rule.name,
            fee_waived=rule.fee_waived,
            recurring_id=recurring_id,
        )
        following = next_recurring_date(
            rule.next_date, rule.frequency, rule.interval_count
        )
        active = True
        if rule.end_date and following > rule.end_date:
            active = False
        self.conn.execute(
            "UPDATE recurring_transactions SET next_date = ?, active = ?, updated_at = ?"
            " WHERE id = ?",
            (following, int(active), now_iso(), recurring_id),
        )
        self.conn.commit()
        return transaction_id

    # ---------------------------------------------------------- reconciliation
    def reconciliations(
        self, account_id: int, *, limit: int = 50
    ) -> list[Reconciliation]:
        rows = self.conn.execute(
            "SELECT id, account_id, date, statement_balance, ledger_balance,"
            " difference, note, created_at FROM account_reconciliations"
            " WHERE account_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (account_id, max(1, int(limit))),
        ).fetchall()
        return [
            Reconciliation(
                id=int(row["id"]),
                account_id=int(row["account_id"]),
                date=row["date"],
                statement_balance=int(row["statement_balance"]),
                ledger_balance=int(row["ledger_balance"]),
                difference=int(row["difference"]),
                note=row["note"] or "",
                created_at=row["created_at"] or "",
            )
            for row in rows
        ]

    def reconcile_account(
        self,
        account_id: int,
        statement_balance: int,
        *,
        day: str | None = None,
        note: str = "",
    ) -> Reconciliation:
        """Align an account's ledger balance to a statement balance.

        The correction is stored on the account as an adjustment (not as
        income/expense), so reports stay clean while the balance becomes
        trustworthy.
        """
        account = self.get_account(account_id, include_archived=True)
        if account.type == "investment":
            raise ValueError("投资账户请使用市值快照校准余额")
        value = int(statement_balance)
        if abs(value) > MAX_AMOUNT_CENTS:
            raise ValueError("对账余额超出可记录范围")
        ledger = account.balance
        difference = value - ledger
        stamp = normalize_day(day) if day else today_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET adjustment = adjustment + ? WHERE id = ?",
                (difference, account_id),
            )
            cursor = conn.execute(
                "INSERT INTO account_reconciliations"
                " (account_id, date, statement_balance, ledger_balance, difference,"
                "  note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    stamp,
                    value,
                    ledger,
                    difference,
                    str(note or "").strip()[:200],
                    now_iso(),
                ),
            )
            reconciliation_id = int(cursor.lastrowid)
        row = self.conn.execute(
            "SELECT * FROM account_reconciliations WHERE id = ?",
            (reconciliation_id,),
        ).fetchone()
        return Reconciliation(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            date=row["date"],
            statement_balance=int(row["statement_balance"]),
            ledger_balance=int(row["ledger_balance"]),
            difference=int(row["difference"]),
            note=row["note"] or "",
            created_at=row["created_at"] or "",
        )

    def delete_reconciliation(self, reconciliation_id: int) -> None:
        row = self.conn.execute(
            "SELECT * FROM account_reconciliations WHERE id = ?",
            (reconciliation_id,),
        ).fetchone()
        if row is None:
            return
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE accounts SET adjustment = adjustment - ? WHERE id = ?",
                (int(row["difference"]), int(row["account_id"])),
            )
            conn.execute(
                "DELETE FROM account_reconciliations WHERE id = ?",
                (reconciliation_id,),
            )

    def _apply_transfer_fee(
        self,
        *,
        account: Account,
        posted: int,
        received: int,
        date: str,
        currency: str,
        target_currency: str,
        fee_waived: bool,
        fee_included: bool | None,
        exclude_transaction_id: int | None = None,
    ) -> tuple[int, bool, int]:
        """Resolve fee, inclusion mode, and the amount reaching the target."""
        if fee_waived:
            return 0, False, received
        fee = self.withdrawal_fee(account.id, posted)
        if not fee:
            return 0, False, received
        available = self._available_before(account.id, exclude_transaction_id)
        if fee_included is None:
            fee_included = posted == available
        if not fee_included:
            if posted + fee > available:
                raise ValueError("提现金额不足以支付手续费")
            return fee, False, received
        net = posted - fee
        if net <= 0:
            raise ValueError("提现金额不足以支付手续费")
        converted = self._converted(net, account.currency, target_currency, date)
        return fee, True, converted

    def add_account(
        self,
        name: str,
        type_: str,
        opening_balance: int = 0,
        note: str = "",
        archived: bool = False,
        currency: str = "CNY",
    ) -> int:
        name = self._clean_name(name, "账户名称", 30)
        if type_ not in ACCOUNT_TYPES:
            raise ValueError("账户类型无效")
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        opening_balance = int(opening_balance)
        if abs(opening_balance) > MAX_AMOUNT_CENTS:
            raise ValueError("期初金额超出可记录范围")
        note = str(note or "").strip()[:200]
        try:
            cursor = self.conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, note, archived, currency, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, type_, opening_balance, note, int(archived), currency, now_iso()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("已存在同名账户") from None
        return int(cursor.lastrowid)

    def update_account(
        self,
        account_id: int,
        *,
        name: str | None = None,
        type_: str | None = None,
        opening_balance: int | None = None,
        note: str | None = None,
        archived: bool | None = None,
        currency: str | None = None,
    ) -> None:
        current = self.get_account(account_id, include_archived=True)
        if current.is_system:
            raise ValueError("系统账户由定期存款自动管理，不能手动修改")
        new_name = current.name if name is None else self._clean_name(name, "账户名称", 30)
        new_type = current.type if type_ is None else type_
        if new_type not in ACCOUNT_TYPES:
            raise ValueError("账户类型无效")
        new_currency = current.currency if currency is None else currency
        if new_currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        if new_currency != current.currency and (
            self.account_usage(account_id)
            or current.valuation_count
            or self.holding_usage(account_id)
        ):
            raise ValueError("该账户已有记录，不能修改币种；请新建一个账户")
        if new_type != "investment" and (
            current.valuation_count or self.holding_usage(account_id)
        ):
            raise ValueError("该账户已有投资记录，不能改为非投资账户")
        new_opening = (
            current.opening_balance if opening_balance is None else int(opening_balance)
        )
        if abs(new_opening) > MAX_AMOUNT_CENTS:
            raise ValueError("期初金额超出可记录范围")
        if current.valuation_count and new_opening != current.opening_balance:
            raise ValueError("该账户已有市值记录，期初余额不再参与余额计算")
        new_note = current.note if note is None else str(note or "").strip()[:200]
        new_archived = current.archived if archived is None else bool(archived)
        try:
            self.conn.execute(
                "UPDATE accounts SET name = ?, type = ?, opening_balance = ?, note = ?,"
                " archived = ?, currency = ? WHERE id = ?",
                (
                    new_name,
                    new_type,
                    new_opening,
                    new_note,
                    int(new_archived),
                    new_currency,
                    account_id,
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("已存在同名账户") from None

    def get_account(self, account_id: int, *, include_archived: bool = False) -> Account:
        for account in self.accounts(include_archived=include_archived):
            if account.id == account_id:
                return account
        raise ValueError("账户不存在")

    def set_account_archived(self, account_id: int, archived: bool) -> None:
        account = self.get_account(account_id, include_archived=True)
        if account.is_system:
            raise ValueError("系统账户由定期存款自动管理，不能归档")
        self.conn.execute(
            "UPDATE accounts SET archived = ? WHERE id = ?", (int(archived), account_id)
        )
        self.conn.commit()

    def delete_account(self, account_id: int) -> None:
        account = self.get_account(account_id, include_archived=True)
        if account.is_system:
            raise ValueError("系统账户由定期存款自动管理，不能删除")
        used = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id = ? OR to_account_id = ?",
            (account_id, account_id),
        ).fetchone()[0]
        if used:
            raise ValueError("该账户已有记录，无法删除；可以改为归档")
        if self.holding_usage(account_id):
            raise ValueError("该账户已有持仓记录，无法删除；可以改为归档")
        remaining = self.conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if remaining <= 1:
            raise ValueError("至少需要保留一个账户")
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()

    def account_usage(self, account_id: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE account_id = ? OR to_account_id = ?",
                (account_id, account_id),
            ).fetchone()[0]
        )

    # -------------------------------------------------------------- valuations
    def valuations(self, account_id: int, *, limit: int | None = None) -> list[AccountValuation]:
        self.get_account(account_id, include_archived=True)
        sql = (
            "SELECT id, account_id, date, value, note, created_at"
            " FROM account_valuations WHERE account_id = ?"
            " ORDER BY date DESC, id DESC"
        )
        params: list[object] = [account_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [
            AccountValuation(
                id=int(row["id"]),
                account_id=int(row["account_id"]),
                date=row["date"],
                value=int(row["value"]),
                note=row["note"] or "",
                created_at=row["created_at"] or "",
            )
            for row in rows
        ]

    def latest_valuation(self, account_id: int) -> AccountValuation | None:
        rows = self.valuations(account_id, limit=1)
        return rows[0] if rows else None

    def valuation_at(self, account_id: int, day: str) -> AccountValuation | None:
        day = normalize_day(day)
        row = self.conn.execute(
            "SELECT id, account_id, date, value, note, created_at"
            " FROM account_valuations"
            " WHERE account_id = ? AND date <= ?"
            " ORDER BY date DESC, id DESC LIMIT 1",
            (account_id, day),
        ).fetchone()
        if not row:
            return None
        return AccountValuation(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            date=row["date"],
            value=int(row["value"]),
            note=row["note"] or "",
            created_at=row["created_at"] or "",
        )

    def _validate_valuation(
        self, account_id: int, day: str, value: int
    ) -> tuple[str, int]:
        account = self.get_account(account_id, include_archived=True)
        if account.type != "investment":
            raise ValueError("只有投资理财账户可以记录市值")
        day = normalize_day(day)
        if day > today_iso():
            raise ValueError("市值日期不能晚于今天")
        value = int(value)
        if value < 0:
            raise ValueError("市值不能为负数")
        if abs(value) > MAX_AMOUNT_CENTS:
            raise ValueError("市值超出可记录范围")
        return day, value

    def set_valuation(
        self, account_id: int, day: str, value: int, note: str = ""
    ) -> int:
        day, value = self._validate_valuation(account_id, day, value)
        note = str(note or "").strip()[:200]
        try:
            self.conn.execute(
                "INSERT INTO account_valuations (account_id, date, value, note, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(account_id, date) DO UPDATE SET"
                " value = excluded.value, note = excluded.note",
                (account_id, day, value, note, now_iso()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("市值记录保存失败") from None
        row = self.conn.execute(
            "SELECT id FROM account_valuations WHERE account_id = ? AND date = ?",
            (account_id, day),
        ).fetchone()
        return int(row["id"])

    def update_valuation(
        self, valuation_id: int, day: str, value: int, note: str = ""
    ) -> None:
        row = self.conn.execute(
            "SELECT * FROM account_valuations WHERE id = ?", (valuation_id,)
        ).fetchone()
        if not row:
            raise ValueError("市值记录不存在")
        day, value = self._validate_valuation(int(row["account_id"]), day, value)
        duplicate = self.conn.execute(
            "SELECT id FROM account_valuations"
            " WHERE account_id = ? AND date = ? AND id <> ?",
            (row["account_id"], day, valuation_id),
        ).fetchone()
        if duplicate:
            raise ValueError("该日期已有市值记录，请直接编辑那一条")
        note = str(note or "").strip()[:200]
        self.conn.execute(
            "UPDATE account_valuations SET date = ?, value = ?, note = ? WHERE id = ?",
            (day, value, note, valuation_id),
        )
        self.conn.commit()

    def delete_valuation(self, valuation_id: int) -> None:
        self.conn.execute("DELETE FROM account_valuations WHERE id = ?", (valuation_id,))
        self.conn.commit()

    # --------------------------------------------------------------- holdings
    @staticmethod
    def _holding(row: sqlite3.Row) -> Holding:
        return Holding(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            name=row["name"],
            symbol=row["symbol"] or "",
            quantity_units=int(row["quantity_units"]),
            cost_price=int(row["cost_price"]),
            price=int(row["price"]),
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            currency=row["currency"] or "CNY",
            account_name=row["account_name"] or "",
            realized_profit=int(row["realized_profit"] or 0),
            dividends=int(row["dividends"] or 0),
            asset_class=row["asset_class"] or "",
            region=row["region"] or "",
        )

    def _validate_holding(
        self,
        account_id: int,
        name: str,
        quantity_units: int,
        cost_price: int,
        price: int,
    ) -> tuple[str, int, int, int]:
        account = self.get_account(account_id, include_archived=True)
        if account.type != "investment":
            raise ValueError("只有投资理财账户可以记录持仓")
        name = self._clean_name(name, "持仓名称", 60)
        quantity_units = int(quantity_units)
        if quantity_units <= 0 or quantity_units > MAX_QUANTITY_UNITS:
            raise ValueError("持仓数量无效")
        for value, label in ((cost_price, "成本价"), (price, "现价")):
            if int(value) < 0 or abs(int(value)) > MAX_AMOUNT_CENTS:
                raise ValueError(f"{label}无效")
        return name, quantity_units, int(cost_price), int(price)

    @staticmethod
    def _validate_holding_returns(
        realized_profit: int, dividends: int
    ) -> tuple[int, int]:
        realized_profit = int(realized_profit or 0)
        dividends = int(dividends or 0)
        if abs(realized_profit) > MAX_AMOUNT_CENTS:
            raise ValueError("已实现收益金额过大")
        if dividends < 0 or dividends > MAX_AMOUNT_CENTS:
            raise ValueError("累计分红不能为负数")
        return realized_profit, dividends

    def holdings(self, account_id: int | None = None) -> list[Holding]:
        sql = (
            "SELECT h.id, h.account_id, h.symbol, h.name, h.quantity_units,"
            " h.cost_price, h.price, h.note, h.created_at, h.realized_profit, h.dividends,"
            " h.asset_class, h.region,"
            " a.currency AS currency, a.name AS account_name"
            " FROM holdings h JOIN accounts a ON a.id = h.account_id"
        )
        params: list[object] = []
        if account_id is not None:
            sql += " WHERE h.account_id = ?"
            params.append(int(account_id))
        sql += " ORDER BY h.account_id, h.symbol, h.name, h.id"
        return [self._holding(row) for row in self.conn.execute(sql, tuple(params))]

    def get_holding(self, holding_id: int) -> Holding:
        row = self.conn.execute(
            "SELECT h.id, h.account_id, h.symbol, h.name, h.quantity_units,"
            " h.cost_price, h.price, h.note, h.created_at, h.realized_profit, h.dividends,"
            " h.asset_class, h.region,"
            " a.currency AS currency, a.name AS account_name"
            " FROM holdings h JOIN accounts a ON a.id = h.account_id WHERE h.id = ?",
            (holding_id,),
        ).fetchone()
        if not row:
            raise ValueError("持仓不存在")
        return self._holding(row)

    def add_holding(
        self,
        account_id: int,
        name: str,
        *,
        symbol: str = "",
        quantity_units: int,
        cost_price: int,
        price: int,
        note: str = "",
        realized_profit: int = 0,
        dividends: int = 0,
        asset_class: str = "",
        region: str = "",
    ) -> int:
        name, quantity_units, cost_price, price = self._validate_holding(
            account_id, name, quantity_units, cost_price, price
        )
        realized_profit, dividends = self._validate_holding_returns(
            realized_profit, dividends
        )
        cursor = self.conn.execute(
            "INSERT INTO holdings (account_id, symbol, name, quantity_units,"
            " cost_price, price, note, realized_profit, dividends,"
            " asset_class, region, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(account_id),
                str(symbol or "").strip().upper()[:20],
                name,
                quantity_units,
                cost_price,
                price,
                str(note or "").strip()[:200],
                realized_profit,
                dividends,
                str(asset_class or "").strip()[:40],
                str(region or "").strip()[:40],
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_holding(
        self,
        holding_id: int,
        *,
        account_id: int,
        name: str,
        symbol: str = "",
        quantity_units: int,
        cost_price: int,
        price: int,
        note: str = "",
        realized_profit: int = 0,
        dividends: int = 0,
        asset_class: str = "",
        region: str = "",
    ) -> None:
        self.get_holding(holding_id)
        name, quantity_units, cost_price, price = self._validate_holding(
            account_id, name, quantity_units, cost_price, price
        )
        realized_profit, dividends = self._validate_holding_returns(
            realized_profit, dividends
        )
        self.conn.execute(
            "UPDATE holdings SET account_id = ?, symbol = ?, name = ?,"
            " quantity_units = ?, cost_price = ?, price = ?, note = ?,"
            " realized_profit = ?, dividends = ?, asset_class = ?, region = ?,"
            " updated_at = ?"
            " WHERE id = ?",
            (
                int(account_id),
                str(symbol or "").strip().upper()[:20],
                name,
                quantity_units,
                cost_price,
                price,
                str(note or "").strip()[:200],
                realized_profit,
                dividends,
                str(asset_class or "").strip()[:40],
                str(region or "").strip()[:40],
                now_iso(),
                holding_id,
            ),
        )
        self.conn.commit()

    def delete_holding(self, holding_id: int) -> None:
        self.conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        self.conn.commit()

    def update_holding_price(self, holding_id: int, price: int) -> None:
        """Update only the market price, used by quote refresh."""
        self.get_holding(holding_id)
        value = int(price)
        if value < 0 or value > MAX_AMOUNT_CENTS:
            raise ValueError("现价超出允许范围")
        self.conn.execute(
            "UPDATE holdings SET price = ?, updated_at = ? WHERE id = ?",
            (value, now_iso(), holding_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------ app metadata
    def meta_get(self, key: str, default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (str(key),)
        ).fetchone()
        return str(row["value"]) if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(key), str(value)),
        )
        self.conn.commit()

    def holdings_summary(self, account_id: int | None = None) -> HoldingsSummary:
        rows = self.holdings(account_id)
        if account_id is None:
            cost = sum(self._to_base(item.cost_value, item.currency) for item in rows)
            market = sum(self._to_base(item.market_value, item.currency) for item in rows)
            realized = sum(
                self._to_base(item.realized_profit, item.currency) for item in rows
            )
            dividends = sum(
                self._to_base(item.dividends, item.currency) for item in rows
            )
        else:
            cost = sum(item.cost_value for item in rows)
            market = sum(item.market_value for item in rows)
            realized = sum(item.realized_profit for item in rows)
            dividends = sum(item.dividends for item in rows)
        return HoldingsSummary(
            cost=cost,
            market=market,
            count=len(rows),
            realized=realized,
            dividends=dividends,
        )

    def portfolio_xirr(self, account_id: int | None = None) -> float | None:
        """Estimate the annualized return from holding cost to today's value."""
        rows = self.holdings(account_id)
        today = date_cls.today()
        flows: list[tuple[date_cls, int]] = []
        for item in rows:
            if item.cost_value <= 0:
                continue
            try:
                start = date_cls.fromisoformat((item.created_at or "")[:10])
            except ValueError:
                start = today
            flows.append(
                (start, -self._to_base(item.cost_value, item.currency, start.isoformat()))
            )
            ending = item.market_value + item.realized_profit + item.dividends
            flows.append(
                (
                    today,
                    self._to_base(ending, item.currency, today.isoformat()),
                )
            )
        return xirr(flows)

    def set_cash_balance(self, account_id: int, target: int) -> int:
        """Set the cash portion of an investment account without touching holdings."""
        account = self.get_account(account_id, include_archived=True)
        if account.type != "investment":
            raise ValueError("只有投资账户可以调整现金")
        target = int(target)
        if target < 0:
            raise ValueError("现金余额不能为负数")
        if target > MAX_AMOUNT_CENTS:
            raise ValueError("金额过大")
        current = account.cash_balance
        delta = target - current
        if delta:
            self.conn.execute(
                "UPDATE accounts SET adjustment = adjustment + ? WHERE id = ?",
                (delta, account_id),
            )
            self.conn.commit()
        return target

    def holding_usage(self, account_id: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM holdings WHERE account_id = ?", (account_id,)
            ).fetchone()[0]
        )

    # -------------------------------------------------------- investment lots
    @staticmethod
    def _investment_trade(row: sqlite3.Row) -> InvestmentTrade:
        return InvestmentTrade(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            symbol=row["symbol"] or "",
            name=row["name"],
            kind=row["kind"],
            trade_date=row["trade_date"],
            quantity_units=int(row["quantity_units"]),
            price=int(row["price"]),
            fee=int(row["fee"]),
            amount=int(row["amount"]),
            currency=row["currency"] or "CNY",
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            account_name=row["account_name"] if "account_name" in row.keys() else "",
        )

    @staticmethod
    def _investment_lot(row: sqlite3.Row) -> InvestmentLot:
        return InvestmentLot(
            id=int(row["id"]),
            trade_id=int(row["trade_id"]),
            account_id=int(row["account_id"]),
            symbol=row["symbol"] or "",
            name=row["name"],
            acquired_date=row["acquired_date"],
            quantity_units=int(row["quantity_units"]),
            remaining_units=int(row["remaining_units"]),
            unit_cost=int(row["unit_cost"]),
            currency=row["currency"] or "CNY",
            created_at=row["created_at"] or "",
        )

    @staticmethod
    def _investment_disposal(row: sqlite3.Row) -> InvestmentDisposal:
        return InvestmentDisposal(
            id=int(row["id"]),
            sell_trade_id=int(row["sell_trade_id"]),
            lot_id=int(row["lot_id"]),
            quantity_units=int(row["quantity_units"]),
            cost=int(row["cost"]),
            proceeds=int(row["proceeds"]),
            realized=int(row["realized"]),
            created_at=row["created_at"] or "",
        )

    def investment_trades(
        self, account_id: int | None = None, *, limit: int | None = None
    ) -> list[InvestmentTrade]:
        sql = (
            "SELECT t.id, t.account_id, t.symbol, t.name, t.kind, t.trade_date,"
            " t.quantity_units, t.price, t.fee, t.amount, t.currency, t.note,"
            " t.created_at, a.name AS account_name"
            " FROM investment_trades t JOIN accounts a ON a.id = t.account_id"
        )
        params: list[object] = []
        if account_id is not None:
            sql += " WHERE t.account_id = ?"
            params.append(int(account_id))
        sql += " ORDER BY t.trade_date DESC, t.id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        return [self._investment_trade(row) for row in self.conn.execute(sql, tuple(params))]

    def investment_lots(
        self, account_id: int | None = None, *, trade_id: int | None = None
    ) -> list[InvestmentLot]:
        sql = "SELECT * FROM investment_lots"
        clauses: list[str] = []
        params: list[object] = []
        if account_id is not None:
            clauses.append("account_id = ?")
            params.append(int(account_id))
        if trade_id is not None:
            clauses.append("trade_id = ?")
            params.append(int(trade_id))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY acquired_date, id"
        return [self._investment_lot(row) for row in self.conn.execute(sql, tuple(params))]

    def investment_disposals(
        self, *, sell_trade_id: int | None = None
    ) -> list[InvestmentDisposal]:
        sql = "SELECT * FROM investment_disposals"
        params: tuple[object, ...] = ()
        if sell_trade_id is not None:
            sql += " WHERE sell_trade_id = ?"
            params = (int(sell_trade_id),)
        sql += " ORDER BY id"
        return [self._investment_disposal(row) for row in self.conn.execute(sql, params)]

    def _investment_account(self, account_id: int) -> Account:
        account = self.get_account(account_id, include_archived=True)
        if account.type != "investment":
            raise ValueError("只有投资理财账户可以记录投资流水")
        return account

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        return str(symbol or "").strip().upper()[:20]

    def _holding_row_for(
        self, conn: sqlite3.Connection, account_id: int, symbol: str, name: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM holdings WHERE account_id = ? AND symbol = ? AND name = ?",
            (int(account_id), symbol, name),
        ).fetchone()

    def _insert_holding(
        self,
        conn: sqlite3.Connection,
        account_id: int,
        symbol: str,
        name: str,
        *,
        quantity_units: int,
        cost_price: int,
        price: int,
    ) -> sqlite3.Row:
        conn.execute(
            "INSERT INTO holdings (account_id, symbol, name, quantity_units,"
            " cost_price, price, note, realized_profit, dividends, asset_class,"
            " region, created_at) VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, '', '', ?)",
            (
                int(account_id), symbol, name, int(quantity_units),
                int(cost_price), int(price), now_iso(),
            ),
        )
        row = self._holding_row_for(conn, account_id, symbol, name)
        assert row is not None
        return row

    def _write_holding_values(
        self,
        conn: sqlite3.Connection,
        holding_id: int,
        *,
        quantity_units: int,
        cost_price: int,
        price: int,
        realized_profit: int,
        dividends: int,
    ) -> None:
        conn.execute(
            "UPDATE holdings SET quantity_units = ?, cost_price = ?, price = ?,"
            " realized_profit = ?, dividends = ?, updated_at = ? WHERE id = ?",
            (
                int(quantity_units),
                int(cost_price),
                int(price),
                int(realized_profit),
                int(dividends),
                now_iso(),
                int(holding_id),
            ),
        )

    def record_investment_trade(
        self,
        account_id: int,
        *,
        kind: str,
        symbol: str,
        name: str,
        trade_date: str,
        quantity_units: int = 0,
        price: int = 0,
        fee: int = 0,
        amount: int = 0,
        note: str = "",
    ) -> int:
        """Record a buy/sell/dividend and keep the aggregate holding in sync."""
        account = self._investment_account(account_id)
        kind = str(kind or "").strip().lower()
        if kind not in ("buy", "sell", "dividend"):
            raise ValueError("投资流水类型无效")
        symbol = self._clean_symbol(symbol)
        name = self._clean_name(name, "持仓名称", 60)
        trade_date = normalize_day(trade_date)
        quantity_units = int(quantity_units or 0)
        price = int(price or 0)
        fee = int(fee or 0)
        amount = int(amount or 0)
        if kind in ("buy", "sell"):
            if quantity_units <= 0 or quantity_units > MAX_QUANTITY_UNITS:
                raise ValueError("成交数量无效")
            if price < 0 or price > MAX_AMOUNT_CENTS:
                raise ValueError("成交价无效")
            if fee < 0 or fee > MAX_AMOUNT_CENTS:
                raise ValueError("手续费无效")
            amount = 0
        else:
            if amount <= 0 or amount > MAX_AMOUNT_CENTS:
                raise ValueError("分红金额无效")
            quantity_units = 0
            price = 0
            fee = 0
        gross = (quantity_units * price + 500_000) // 1_000_000
        if kind == "sell" and fee > gross:
            raise ValueError("手续费不能超过成交金额")
        with self.db.transaction() as conn:
            trade = conn.execute(
                "INSERT INTO investment_trades (account_id, symbol, name, kind,"
                " trade_date, quantity_units, price, fee, amount, currency, note,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(account_id), symbol, name, kind, trade_date,
                    quantity_units, price, fee, amount, account.currency,
                    str(note or "").strip()[:200], now_iso(),
                ),
            )
            trade_id = int(trade.lastrowid)
            holding = self._holding_row_for(conn, account_id, symbol, name)
            old_qty = int(holding["quantity_units"]) if holding is not None else 0
            old_cost = (
                (old_qty * int(holding["cost_price"]) + 500_000) // 1_000_000
                if holding is not None else 0
            )
            realized = int(holding["realized_profit"] or 0) if holding is not None else 0
            dividends = int(holding["dividends"] or 0) if holding is not None else 0
            if kind == "buy":
                total_cost = gross + fee
                unit_cost = (
                    (total_cost * 1_000_000 + quantity_units // 2) // quantity_units
                    if quantity_units
                    else 0
                )
                conn.execute(
                    "INSERT INTO investment_lots (trade_id, account_id, symbol, name,"
                    " acquired_date, quantity_units, remaining_units, unit_cost,"
                    " currency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trade_id, int(account_id), symbol, name, trade_date,
                        quantity_units, quantity_units, unit_cost, account.currency,
                        now_iso(),
                    ),
                )
                if holding is None:
                    self._insert_holding(
                        conn, account_id, symbol, name,
                        quantity_units=quantity_units, cost_price=unit_cost, price=price,
                    )
                    return trade_id
                new_qty = old_qty + quantity_units
                new_cost = old_cost + total_cost
                new_price = int(holding["price"]) or price
            elif kind == "sell":
                if holding is None:
                    raise ValueError("当前没有可卖出的持仓")
                if quantity_units > old_qty:
                    raise ValueError("卖出数量超过当前持仓")
                open_lots = [
                    row
                    for row in conn.execute(
                        "SELECT * FROM investment_lots WHERE account_id = ? AND"
                        " symbol = ? AND name = ? AND remaining_units > 0"
                        " ORDER BY acquired_date, id",
                        (int(account_id), symbol, name),
                    )
                ]
                available = sum(int(row["remaining_units"]) for row in open_lots)
                if quantity_units > available:
                    raise ValueError("卖出数量超过可用的逐笔持仓")
                left = quantity_units
                cost_total = 0
                proceeds = gross - fee
                proceeds_left = proceeds
                for index, lot in enumerate(open_lots):
                    if left <= 0:
                        break
                    take = min(left, int(lot["remaining_units"]))
                    lot_cost = (take * int(lot["unit_cost"]) + 500_000) // 1_000_000
                    if index == len(open_lots) - 1 or take == left:
                        lot_proceeds = proceeds_left
                    else:
                        lot_proceeds = (proceeds * take + quantity_units // 2) // quantity_units
                        lot_proceeds = min(lot_proceeds, proceeds_left)
                    proceeds_left -= lot_proceeds
                    conn.execute(
                        "UPDATE investment_lots SET remaining_units = remaining_units - ?"
                        " WHERE id = ?",
                        (take, int(lot["id"])),
                    )
                    conn.execute(
                        "INSERT INTO investment_disposals (sell_trade_id, lot_id,"
                        " quantity_units, cost, proceeds, realized, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            trade_id, int(lot["id"]), take, lot_cost, lot_proceeds,
                            lot_proceeds - lot_cost, now_iso(),
                        ),
                    )
                    cost_total += lot_cost
                    left -= take
                if left > 0:
                    raise ValueError("卖出数量超过可用的逐笔持仓")
                new_qty = old_qty - quantity_units
                new_cost = max(0, old_cost - cost_total)
                realized += proceeds - cost_total
                new_price = price or int(holding["price"])
            else:
                if holding is None:
                    return trade_id
                new_qty = old_qty
                new_cost = old_cost
                dividends += amount
                new_price = int(holding["price"])
            new_cost_price = (
                (new_cost * 1_000_000 + new_qty // 2) // new_qty if new_qty else 0
            )
            self._write_holding_values(
                conn,
                int(holding["id"]),
                quantity_units=new_qty,
                cost_price=new_cost_price,
                price=new_price,
                realized_profit=realized,
                dividends=dividends,
            )
            return trade_id

    # ------------------------------------------------------------ fixed assets
    @staticmethod
    def _fixed_asset(row: sqlite3.Row) -> FixedAsset:
        return FixedAsset(
            id=int(row["id"]),
            name=row["name"],
            type=row["type"],
            purchase_price=int(row["purchase_price"]),
            current_value=int(row["current_value"]),
            valuation_date=row["valuation_date"],
            currency=row["currency"] or "CNY",
            note=row["note"] or "",
            created_at=row["created_at"] or "",
        )

    @staticmethod
    def _fixed_asset_valuation(row: sqlite3.Row) -> FixedAssetValuation:
        return FixedAssetValuation(
            id=int(row["id"]),
            asset_id=int(row["asset_id"]),
            value=int(row["value"]),
            valued_on=row["valued_on"],
            note=row["note"] or "",
            created_at=row["created_at"] or "",
        )

    def _record_fixed_valuation(
        self, asset_id: int, value: int, valued_on: str, note: str = ""
    ) -> None:
        self.conn.execute(
            "INSERT INTO fixed_asset_valuations"
            " (asset_id, value, valued_on, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(asset_id, valued_on)"
            " DO UPDATE SET value=excluded.value, note=excluded.note",
            (asset_id, int(value), valued_on, note, now_iso()),
        )

    def _validate_fixed_asset(
        self,
        name: str,
        type_: str,
        purchase_price: int,
        current_value: int,
        valuation_date: str,
        currency: str,
        note: str,
    ) -> tuple[str, str, int, int, str, str, str]:
        name = self._clean_name(name, "资产名称", 60)
        if type_ not in FIXED_ASSET_TYPE_META:
            raise ValueError("不支持的固定资产类型")
        purchase_price = int(purchase_price)
        current_value = int(current_value)
        if purchase_price < 0 or current_value < 0:
            raise ValueError("资产金额不能为负数")
        if purchase_price > MAX_AMOUNT_CENTS or current_value > MAX_AMOUNT_CENTS:
            raise ValueError("金额过大")
        valuation_date = normalize_day(valuation_date)
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        note = str(note or "").strip()
        if len(note) > 200:
            raise ValueError("备注不能超过 200 个字符")
        return name, type_, purchase_price, current_value, valuation_date, currency, note

    def fixed_assets(self) -> list[FixedAsset]:
        rows = self.conn.execute(
            "SELECT * FROM fixed_assets ORDER BY current_value DESC, id"
        ).fetchall()
        return [self._fixed_asset(row) for row in rows]

    def get_fixed_asset(self, asset_id: int) -> FixedAsset:
        row = self.conn.execute(
            "SELECT * FROM fixed_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if not row:
            raise ValueError("固定资产不存在")
        return self._fixed_asset(row)

    def add_fixed_asset(
        self,
        name: str,
        type_: str,
        purchase_price: int,
        current_value: int,
        valuation_date: str,
        *,
        currency: str = "CNY",
        note: str = "",
    ) -> int:
        values = self._validate_fixed_asset(
            name, type_, purchase_price, current_value, valuation_date, currency, note
        )
        stamp = now_iso()
        cursor = self.conn.execute(
            "INSERT INTO fixed_assets"
            " (name, type, purchase_price, current_value, valuation_date, currency, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (*values, stamp),
        )
        asset_id = int(cursor.lastrowid)
        self._record_fixed_valuation(
            asset_id, int(values[3]), str(values[4])
        )
        self.conn.commit()
        return asset_id

    def update_fixed_asset(
        self,
        asset_id: int,
        *,
        name: str,
        type_: str,
        purchase_price: int,
        current_value: int,
        valuation_date: str,
        currency: str = "CNY",
        note: str = "",
    ) -> None:
        self.get_fixed_asset(asset_id)
        values = self._validate_fixed_asset(
            name, type_, purchase_price, current_value, valuation_date, currency, note
        )
        self.conn.execute(
            "UPDATE fixed_assets SET name=?, type=?, purchase_price=?, current_value=?,"
            " valuation_date=?, currency=?, note=?, updated_at=? WHERE id=?",
            (*values, now_iso(), asset_id),
        )
        self._record_fixed_valuation(
            asset_id, int(values[3]), str(values[4]), str(values[6])
        )
        self.conn.commit()

    def delete_fixed_asset(self, asset_id: int) -> None:
        self.conn.execute("DELETE FROM fixed_assets WHERE id = ?", (asset_id,))
        self.conn.commit()

    def fixed_asset_value(self) -> int:
        total = 0
        for asset in self.fixed_assets():
            total += self._to_base(asset.current_value, asset.currency, asset.valuation_date)
        return total

    def fixed_asset_valuations(
        self, asset_id: int | None = None
    ) -> list[FixedAssetValuation]:
        if asset_id is None:
            rows = self.conn.execute(
                "SELECT * FROM fixed_asset_valuations"
                " ORDER BY valued_on DESC, id DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM fixed_asset_valuations WHERE asset_id = ?"
                " ORDER BY valued_on DESC, id DESC",
                (asset_id,),
            ).fetchall()
        return [self._fixed_asset_valuation(row) for row in rows]

    def record_fixed_asset_valuation(
        self, asset_id: int, value: int, valued_on: str, note: str = ""
    ) -> None:
        asset = self.get_fixed_asset(asset_id)
        value = int(value)
        if value < 0 or value > MAX_AMOUNT_CENTS:
            raise ValueError("资产金额无效")
        day = normalize_day(valued_on)
        if day < asset.valuation_date:
            # Historical entries are kept as a series, not used to rewrite
            # the current value backwards.
            self._record_fixed_valuation(asset_id, value, day, note)
            self.conn.commit()
            return
        self.conn.execute(
            "UPDATE fixed_assets SET current_value = ?, valuation_date = ?,"
            " updated_at = ? WHERE id = ?",
            (value, day, now_iso(), asset_id),
        )
        self._record_fixed_valuation(asset_id, value, day, note)
        self.conn.commit()

    def fixed_asset_value_at(self, cutoff: str) -> int:
        day = normalize_day(cutoff)
        rows = self.conn.execute(
            """
            SELECT fa.currency,
                   COALESCE((
                       SELECT v.value FROM fixed_asset_valuations v
                       WHERE v.asset_id = fa.id AND v.valued_on <= ?
                       ORDER BY v.valued_on DESC LIMIT 1
                   ), fa.purchase_price) AS value
            FROM fixed_assets fa
            """,
            (day,),
        ).fetchall()
        total = 0
        for row in rows:
            total += self._to_base(int(row["value"]), row["currency"], day)
        return total

    # --------------------------------------------------------------- savings
    @staticmethod
    def _savings_goal(row: sqlite3.Row) -> SavingsGoal:
        return SavingsGoal(
            id=int(row["id"]),
            name=row["name"],
            target_amount=int(row["target_amount"]),
            saved_amount=int(row["saved_amount"]),
            target_date=row["target_date"],
            note=row["note"] or "",
            archived=bool(row["archived"]),
            created_at=row["created_at"] or "",
        )

    def savings_goals(self, *, include_archived: bool = False) -> list[SavingsGoal]:
        sql = "SELECT * FROM savings_goals"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY (target_date IS NULL), target_date, id"
        return [self._savings_goal(row) for row in self.conn.execute(sql)]

    def get_savings_goal(self, goal_id: int) -> SavingsGoal:
        row = self.conn.execute(
            "SELECT * FROM savings_goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if not row:
            raise ValueError("储蓄目标不存在")
        return self._savings_goal(row)

    def add_savings_goal(
        self,
        name: str,
        target_amount: int,
        *,
        saved_amount: int = 0,
        target_date: str | None = None,
        note: str = "",
    ) -> int:
        name = self._clean_name(name, "目标名称", 60)
        target_amount = int(target_amount)
        saved_amount = int(saved_amount)
        if target_amount <= 0 or target_amount > MAX_AMOUNT_CENTS:
            raise ValueError("目标金额必须大于 0")
        if saved_amount < 0 or saved_amount > MAX_AMOUNT_CENTS:
            raise ValueError("已存金额无效")
        day = normalize_day(target_date) if target_date else None
        cursor = self.conn.execute(
            "INSERT INTO savings_goals (name, target_amount, saved_amount,"
            " target_date, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, target_amount, saved_amount, day, str(note or "").strip()[:200], now_iso()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_savings_goal(
        self,
        goal_id: int,
        *,
        name: str,
        target_amount: int,
        saved_amount: int,
        target_date: str | None = None,
        note: str = "",
    ) -> None:
        self.get_savings_goal(goal_id)
        name = self._clean_name(name, "目标名称", 60)
        target_amount = int(target_amount)
        saved_amount = int(saved_amount)
        if target_amount <= 0 or target_amount > MAX_AMOUNT_CENTS:
            raise ValueError("目标金额必须大于 0")
        if saved_amount < 0 or saved_amount > MAX_AMOUNT_CENTS:
            raise ValueError("已存金额无效")
        day = normalize_day(target_date) if target_date else None
        self.conn.execute(
            "UPDATE savings_goals SET name = ?, target_amount = ?, saved_amount = ?,"
            " target_date = ?, note = ?, updated_at = ? WHERE id = ?",
            (name, target_amount, saved_amount, day, str(note or "").strip()[:200], now_iso(), goal_id),
        )
        self.conn.commit()

    def add_goal_funds(self, goal_id: int, delta: int) -> None:
        goal = self.get_savings_goal(goal_id)
        saved = max(0, goal.saved_amount + int(delta))
        if saved > MAX_AMOUNT_CENTS:
            raise ValueError("已存金额超出可记录范围")
        self.conn.execute(
            "UPDATE savings_goals SET saved_amount = ?, updated_at = ? WHERE id = ?",
            (saved, now_iso(), goal_id),
        )
        self.conn.commit()

    def delete_savings_goal(self, goal_id: int) -> None:
        self.conn.execute("DELETE FROM savings_goals WHERE id = ?", (goal_id,))
        self.conn.commit()

    # --------------------------------------------------------- term deposits
    @staticmethod
    def _term_deposit(row: sqlite3.Row) -> TermDeposit:
        return TermDeposit(
            id=int(row["id"]),
            name=row["name"],
            principal=int(row["principal"]),
            currency=row["currency"] or "CNY",
            annual_rate_bp=int(row["annual_rate_bp"]),
            term_months=int(row["term_months"]),
            start_date=row["start_date"],
            maturity_date=row["maturity_date"],
            early_rate_bp=int(row["early_rate_bp"]),
            source_account_id=int(row["source_account_id"]),
            deposit_account_id=int(row["deposit_account_id"]),
            destination_account_id=int(row["destination_account_id"]),
            status=row["status"],
            close_reason=row["close_reason"] or "",
            interest_paid=int(row["interest_paid"] or 0),
            closed_at=row["closed_at"] or "",
            note=row["note"] or "",
            created_at=row["created_at"] or "",
            source_account_name=row["source_account_name"] or "",
            deposit_account_name=row["deposit_account_name"] or "",
            destination_account_name=row["destination_account_name"] or "",
        )

    def deposit_account(self, currency: str) -> Account:
        """Return (creating if needed) the shared virtual deposit account."""
        currency = currency or "CNY"
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM accounts WHERE is_system = 1 AND currency = ?"
                " ORDER BY id LIMIT 1",
                (currency,),
            ).fetchone()
            if row:
                return self.get_account(int(row["id"]), include_archived=True)
            base = "定期存款" if currency == "CNY" else f"定期存款 · {currency}"
            for name in (base, f"{base}（系统）"):
                try:
                    cursor = conn.execute(
                        "INSERT INTO accounts (name, type, opening_balance, note,"
                        " archived, currency, is_system, created_at)"
                        " VALUES (?, 'investment', 0, '系统自动创建的定期存款账户',"
                        " 0, ?, 1, ?)",
                        (name, currency, now_iso()),
                    )
                    return self.get_account(int(cursor.lastrowid), include_archived=True)
                except sqlite3.IntegrityError:
                    continue
        raise ValueError("无法创建定期存款账户")

    def term_deposits(self, *, include_closed: bool = True) -> list[TermDeposit]:
        sql = (
            "SELECT d.*, sa.name AS source_account_name,"
            " da.name AS deposit_account_name,"
            " ta.name AS destination_account_name"
            " FROM term_deposits d"
            " JOIN accounts sa ON sa.id = d.source_account_id"
            " JOIN accounts da ON da.id = d.deposit_account_id"
            " JOIN accounts ta ON ta.id = d.destination_account_id"
        )
        if not include_closed:
            sql += " WHERE d.status = 'active'"
        sql += (
            " ORDER BY CASE d.status WHEN 'active' THEN 0 ELSE 1 END,"
            " d.maturity_date, d.id"
        )
        return [self._term_deposit(row) for row in self.conn.execute(sql)]

    def get_term_deposit(self, deposit_id: int) -> TermDeposit:
        row = self.conn.execute(
            "SELECT d.*, sa.name AS source_account_name,"
            " da.name AS deposit_account_name,"
            " ta.name AS destination_account_name"
            " FROM term_deposits d"
            " JOIN accounts sa ON sa.id = d.source_account_id"
            " JOIN accounts da ON da.id = d.deposit_account_id"
            " JOIN accounts ta ON ta.id = d.destination_account_id"
            " WHERE d.id = ?",
            (deposit_id,),
        ).fetchone()
        if not row:
            raise ValueError("定期存款不存在")
        return self._term_deposit(row)

    def _validate_deposit_accounts(
        self, source: Account, destination: Account, currency: str
    ) -> None:
        for account in (source, destination):
            if account.is_system:
                raise ValueError("请选择普通账户，不能使用系统存款账户")
            if account.type not in ("cash", "debit", "investment"):
                raise ValueError("只能从现金、储蓄或投资账户存入")
            if account.currency != currency:
                raise ValueError("存款币种必须与账户币种一致")

    def add_term_deposit(
        self,
        name: str,
        principal: int,
        currency: str,
        annual_rate_bp: int,
        term_months: int,
        start_date: str,
        early_rate_bp: int,
        source_account_id: int,
        destination_account_id: int,
        *,
        note: str = "",
    ) -> int:
        name = self._clean_name(name, "存款名称", 60)
        principal = int(principal)
        annual_rate_bp = int(annual_rate_bp)
        term_months = int(term_months)
        early_rate_bp = int(early_rate_bp)
        if principal <= 0 or principal > MAX_AMOUNT_CENTS:
            raise ValueError("存款金额必须大于 0")
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        if not 0 <= annual_rate_bp <= 10_000:
            raise ValueError("年利率应在 0% 到 100% 之间")
        if not 1 <= term_months <= 600:
            raise ValueError("存款期限应在 1 到 600 个月之间")
        if not 0 <= early_rate_bp <= 10_000:
            raise ValueError("活期利率应在 0% 到 100% 之间")
        start = normalize_day(start_date) if start_date else today_iso()
        maturity = add_months(start, term_months)
        source = self.get_account(source_account_id)
        destination = self.get_account(destination_account_id)
        self._validate_deposit_accounts(source, destination, currency)
        if source.cash_balance < principal:
            raise ValueError("转出账户余额不足")
        account = self.deposit_account(currency)
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO term_deposits (name, principal, currency,"
                " annual_rate_bp, term_months, start_date, maturity_date,"
                " early_rate_bp, source_account_id, deposit_account_id,"
                " destination_account_id, status, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    name,
                    principal,
                    currency,
                    annual_rate_bp,
                    term_months,
                    start,
                    maturity,
                    early_rate_bp,
                    source.id,
                    account.id,
                    destination.id,
                    str(note or "").strip()[:200],
                    now_iso(),
                ),
            )
            deposit_id = int(cursor.lastrowid)
            self._insert_internal_transfer(
                conn,
                day=start,
                amount=principal,
                currency=currency,
                from_account_id=source.id,
                to_account_id=account.id,
                note=f"存入定期：{name}",
            )
        return deposit_id

    def close_term_deposit(
        self,
        deposit_id: int,
        *,
        destination_account_id: int | None = None,
        on: str | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        deposit = self.get_term_deposit(deposit_id)
        if not deposit.is_active:
            raise ValueError("该定期存款已支取")
        account_id = destination_account_id or deposit.destination_account_id
        destination = self.get_account(account_id)
        self._validate_deposit_accounts(
            self.get_account(deposit.source_account_id), destination, deposit.currency
        )
        as_of = normalize_day(on) if on else today_iso()
        if as_of < deposit.start_date:
            raise ValueError("支取日期不能早于存入日期")
        matured = as_of >= deposit.maturity_date
        close_reason = reason or ("matured" if matured else "early")
        if close_reason not in ("matured", "early"):
            raise ValueError("支取方式无效")
        interest = (
            deposit.maturity_interest
            if close_reason == "matured"
            else deposit.early_interest(as_of)
        )
        virtual = self.get_account(deposit.deposit_account_id, include_archived=True)
        if virtual.cash_balance < deposit.principal:
            raise ValueError("存款账户余额不足，可能已被其他记录占用")
        category = self.find_category("利息收入", "income")
        with self.db.transaction() as conn:
            transfer_id = self._insert_internal_transfer(
                conn,
                day=as_of,
                amount=deposit.principal,
                currency=deposit.currency,
                from_account_id=deposit.deposit_account_id,
                to_account_id=destination.id,
                note=(
                    f"到期支取：{deposit.name}"
                    if close_reason == "matured"
                    else f"提前支取：{deposit.name}"
                ),
            )
            income_id = None
            if interest > 0:
                if category is None:
                    cursor = conn.execute(
                        "INSERT INTO categories (name, kind, color, created_at)"
                        " VALUES ('利息收入', 'income', '#2F9E6E', ?)",
                        (now_iso(),),
                    )
                    category_id = int(cursor.lastrowid)
                else:
                    category_id = category.id
                income_id = self._insert_income(
                    conn,
                    day=as_of,
                    amount=interest,
                    currency=deposit.currency,
                    account_id=destination.id,
                    category_id=category_id,
                    payee=deposit.name,
                    note="定期存款利息",
                )
            conn.execute(
                "UPDATE term_deposits SET status = 'closed', close_reason = ?,"
                " interest_paid = ?, closed_at = ?, updated_at = ? WHERE id = ?",
                (close_reason, interest, as_of, now_iso(), deposit.id),
            )
        return {
            "deposit": deposit,
            "interest": interest,
            "total": deposit.principal + interest,
            "reason": close_reason,
            "transfer_id": transfer_id,
            "income_id": income_id,
            "date": as_of,
        }

    @staticmethod
    def _insert_internal_transfer(
        conn: sqlite3.Connection,
        *,
        day: str,
        amount: int,
        currency: str,
        from_account_id: int,
        to_account_id: int,
        note: str,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO transactions (date, kind, amount, currency,"
            " account_amount, to_amount, fee, fee_waived, fee_included,"
            " recurring_id, refund_of_id, category_id, account_id,"
            " to_account_id, payee, note, import_hash, created_at)"
            " VALUES (?, 'transfer', ?, ?, ?, ?, 0, 0, 0, NULL, NULL, NULL,"
            " ?, ?, '', ?, NULL, ?)",
            (
                day,
                amount,
                currency,
                amount,
                amount,
                from_account_id,
                to_account_id,
                note,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_income(
        conn: sqlite3.Connection,
        *,
        day: str,
        amount: int,
        currency: str,
        account_id: int,
        category_id: int,
        payee: str,
        note: str,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO transactions (date, kind, amount, currency,"
            " account_amount, to_amount, fee, fee_waived, fee_included,"
            " recurring_id, refund_of_id, category_id, account_id,"
            " to_account_id, payee, note, import_hash, created_at)"
            " VALUES (?, 'income', ?, ?, ?, 0, 0, 0, 0, NULL, NULL, ?, ?,"
            " NULL, ?, ?, NULL, ?)",
            (
                day,
                amount,
                currency,
                amount,
                category_id,
                account_id,
                payee,
                note,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)

    def matured_term_deposits(self) -> list[TermDeposit]:
        return [
            deposit
            for deposit in self.term_deposits(include_closed=False)
            if deposit.is_matured
        ]

    # ------------------------------------------------------------- categories
    def categories(self, kind: str | None = None) -> list[Category]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM categories WHERE kind = ? ORDER BY id", (kind,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM categories ORDER BY kind, id"
            ).fetchall()
        return [self._category(row) for row in rows]

    def get_category(self, category_id: int) -> Category:
        row = self.conn.execute(
            "SELECT * FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if not row:
            raise ValueError("分类不存在")
        return self._category(row)

    def find_category(self, name: str, kind: str) -> Category | None:
        row = self.conn.execute(
            "SELECT * FROM categories WHERE name = ? AND kind = ?", (name, kind)
        ).fetchone()
        return self._category(row) if row else None

    def category_usage(self, category_id: int) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE category_id = ?",
                (category_id,),
            ).fetchone()[0]
        )

    def add_category(self, name: str, kind: str, color: str = "#95A0B5") -> int:
        name = self._clean_name(name, "分类名称", 20)
        if kind not in ("expense", "income"):
            raise ValueError("分类类型无效")
        if not _valid_color(color):
            raise ValueError("分类颜色无效")
        try:
            cursor = self.conn.execute(
                "INSERT INTO categories (name, kind, color, created_at) VALUES (?, ?, ?, ?)",
                (name, kind, color, now_iso()),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("该分类已存在") from None
        return int(cursor.lastrowid)

    def update_category(
        self, category_id: int, *, name: str | None = None, color: str | None = None
    ) -> None:
        current = self.get_category(category_id)
        new_name = current.name if name is None else self._clean_name(name, "分类名称", 20)
        new_color = current.color if color is None else color
        if not _valid_color(new_color):
            raise ValueError("分类颜色无效")
        try:
            self.conn.execute(
                "UPDATE categories SET name = ?, color = ? WHERE id = ?",
                (new_name, new_color, category_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("该分类已存在") from None

    def delete_category(self, category_id: int) -> str:
        """Delete a category, moving its rows to “其他”. Returns fallback name."""
        current = self.get_category(category_id)
        fallback = self.find_category(FALLBACK_CATEGORY, current.kind)
        if fallback is None or fallback.id == category_id:
            others = [
                cat
                for cat in self.categories(current.kind)
                if cat.id != category_id
            ]
            if not others:
                raise ValueError("每种类型至少需要保留一个分类")
            fallback = others[0]
        with self.db.transaction():
            self.conn.execute(
                "UPDATE transactions SET category_id = ? WHERE category_id = ?",
                (fallback.id, category_id),
            )
            self.conn.execute("DELETE FROM budgets WHERE category_id = ?", (category_id,))
            self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        return fallback.name

    # ----------------------------------------------------------- transactions
    def _hydrate(self, transactions: list[Transaction]) -> list[Transaction]:
        """Attach splits, tags and attachment metadata without N+1 queries."""
        if not transactions:
            return transactions
        ids = tuple(transaction.id for transaction in transactions)
        placeholders = ",".join("?" for _ in ids)

        tag_map: dict[int, list[Tag]] = {}
        for row in self.conn.execute(
            "SELECT tt.transaction_id, g.id, g.name, g.color FROM transaction_tags tt"
            " JOIN tags g ON g.id = tt.tag_id WHERE tt.transaction_id IN ("
            + placeholders
            + ") ORDER BY g.name",
            ids,
        ):
            tag_map.setdefault(int(row["transaction_id"]), []).append(
                Tag(int(row[1]), row[2], row[3] or "#5B8DEF")
            )

        split_map: dict[int, list[TransactionSplit]] = {}
        for row in self.conn.execute(
            "SELECT s.id, s.transaction_id, s.category_id, c.name, c.color,"
            " s.amount, s.note, s.position FROM transaction_splits s"
            " JOIN categories c ON c.id = s.category_id"
            " WHERE s.transaction_id IN (" + placeholders + ")"
            " ORDER BY s.transaction_id, s.position, s.id",
            ids,
        ):
            split_map.setdefault(int(row["transaction_id"]), []).append(
                TransactionSplit(
                    id=int(row["id"]),
                    transaction_id=int(row["transaction_id"]),
                    category_id=int(row["category_id"]),
                    category_name=row["name"] or "",
                    category_color=row["color"] or "",
                    amount=int(row["amount"]),
                    note=row["note"] or "",
                    position=int(row["position"]),
                )
            )

        attachment_map: dict[int, list[Attachment]] = {}
        for row in self.conn.execute(
            "SELECT id, transaction_id, filename, stored_name, mime_type, size,"
            " created_at FROM attachments WHERE transaction_id IN ("
            + placeholders
            + ") ORDER BY created_at, id",
            ids,
        ):
            attachment_map.setdefault(int(row["transaction_id"]), []).append(
                Attachment(
                    id=int(row["id"]),
                    transaction_id=int(row["transaction_id"]),
                    filename=row["filename"],
                    stored_name=row["stored_name"],
                    mime_type=row["mime_type"] or "",
                    size=int(row["size"] or 0),
                    created_at=row["created_at"] or "",
                )
            )

        return [
            replace(
                transaction,
                tags=tuple(tag_map.get(transaction.id, ())),
                splits=tuple(split_map.get(transaction.id, ())),
                attachments=tuple(attachment_map.get(transaction.id, ())),
            )
            for transaction in transactions
        ]

    def _where_clause(self, filters: TransactionFilter) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.month:
            start, end = month_bounds(filters.month)
            clauses.append("t.date >= ? AND t.date < ?")
            params.extend([start, end])
        if filters.start_date:
            clauses.append("t.date >= ?")
            params.append(filters.start_date)
        if filters.end_date:
            clauses.append("t.date <= ?")
            params.append(filters.end_date)
        if filters.kind:
            clauses.append("t.kind = ?")
            params.append(filters.kind)
        if filters.category_id:
            clauses.append(
                "(t.category_id = ? OR EXISTS (SELECT 1 FROM transaction_splits xs"
                " WHERE xs.transaction_id = t.id AND xs.category_id = ?))"
            )
            params.extend([filters.category_id, filters.category_id])
        if filters.account_id:
            clauses.append("(t.account_id = ? OR t.to_account_id = ?)")
            params.extend([filters.account_id, filters.account_id])
        if filters.tag_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM transaction_tags xt"
                " WHERE xt.transaction_id = t.id AND xt.tag_id = ?)"
            )
            params.append(filters.tag_id)
        search = (filters.search or "").strip()
        if search:
            like = f"%{search}%"
            clauses.append(
                "(t.payee LIKE ? OR t.note LIKE ? OR COALESCE(c.name,'') LIKE ?"
                " OR a.name LIKE ? OR COALESCE(ta.name,'') LIKE ?"
                " OR EXISTS (SELECT 1 FROM transaction_tags xt"
                " JOIN tags g ON g.id = xt.tag_id"
                " WHERE xt.transaction_id = t.id AND g.name LIKE ?))"
            )
            params.extend([like, like, like, like, like, like])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where, params

    def transactions(self, filters: TransactionFilter | None = None) -> list[Transaction]:
        filters = filters or TransactionFilter()
        where, params = self._where_clause(filters)
        limit = max(1, min(int(filters.limit), 100_000))
        rows = self.conn.execute(
            _TXN_SELECT
            + where
            + " ORDER BY t.date DESC, t.id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return self._hydrate([self._transaction(row) for row in rows])

    def transaction_balances(
        self, transaction_ids: Iterable[int] | None = None
    ) -> dict[int, TransactionBalance]:
        """Return the account balance right after each requested transaction.

        The ledger is replayed in posting order so filtered views still show
        the real balance rather than a subtotal of the visible rows.  For
        investment accounts, a valuation dated on the transaction day is the
        end-of-day balance (it already includes that day's trades); later
        snapshots are treated as a new baseline.
        """
        wanted: set[int] | None = None
        if transaction_ids is not None:
            wanted = {int(value) for value in transaction_ids}
            if not wanted:
                return {}

        opening = {
            int(row["id"]): int(row["opening_balance"])
            for row in self.conn.execute("SELECT id, opening_balance FROM accounts")
        }
        if not opening:
            return {}
        rows = self.conn.execute(
            "SELECT id, date, kind, account_id, to_account_id,"
            " account_amount, to_amount, fee, fee_included FROM transactions"
            " ORDER BY date, id"
        ).fetchall()
        if not rows:
            return {}

        valuations: dict[int, list[tuple[str, int]]] = {}
        for row in self.conn.execute(
            "SELECT account_id, date, value FROM account_valuations"
            " ORDER BY account_id, date"
        ):
            valuations.setdefault(int(row["account_id"]), []).append(
                (row["date"], int(row["value"]))
            )

        ledger = dict(opening)
        running: dict[int, tuple[int, int | None]] = {}
        history: dict[int, list[tuple[str, int]]] = {}
        for row in rows:
            txn_id = int(row["id"])
            account_id = int(row["account_id"])
            target_id = (
                int(row["to_account_id"]) if row["to_account_id"] is not None else None
            )
            amount = int(row["account_amount"] or 0)
            if row["kind"] == "income":
                ledger[account_id] = ledger.get(account_id, 0) + amount
            elif row["kind"] == "expense":
                ledger[account_id] = ledger.get(account_id, 0) - amount
            else:
                fee = 0 if bool(row["fee_included"]) else int(row["fee"] or 0)
                ledger[account_id] = (
                    ledger.get(account_id, 0) - amount - fee
                )
                if target_id is not None:
                    ledger[target_id] = (
                        ledger.get(target_id, 0) + int(row["to_amount"] or 0)
                    )
            running[txn_id] = (
                ledger[account_id],
                ledger.get(target_id) if target_id is not None else None,
            )
            history.setdefault(account_id, []).append(
                (row["date"], ledger[account_id])
            )
            if target_id is not None:
                history.setdefault(target_id, []).append(
                    (row["date"], ledger[target_id])
                )

        def effective(account_id: int, day: str, ledger_value: int) -> int:
            series = valuations.get(account_id)
            if not series:
                return ledger_value
            snapshot: tuple[str, int] | None = None
            for item in series:
                if item[0] <= day:
                    snapshot = item
                else:
                    break
            if snapshot is None:
                return ledger_value
            snapshot_day, snapshot_value = snapshot
            if snapshot_day == day:
                return snapshot_value
            base = opening[account_id]
            for entry_day, entry_balance in reversed(history.get(account_id, [])):
                if entry_day <= snapshot_day:
                    base = entry_balance
                    break
            return snapshot_value + ledger_value - base

        result: dict[int, TransactionBalance] = {}
        for row in rows:
            txn_id = int(row["id"])
            if wanted is not None and txn_id not in wanted:
                continue
            source_balance, target_balance = running[txn_id]
            source_id = int(row["account_id"])
            target_id = (
                int(row["to_account_id"]) if row["to_account_id"] is not None else None
            )
            result[txn_id] = TransactionBalance(
                account_balance=effective(
                    source_id, row["date"], source_balance
                ),
                to_account_balance=(
                    effective(target_id, row["date"], target_balance)
                    if target_id is not None and target_balance is not None
                    else None
                ),
            )
        return result

    def count_transactions(self, filters: TransactionFilter | None = None) -> int:
        filters = filters or TransactionFilter()
        where, params = self._where_clause(filters)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM transactions t"
            " JOIN accounts a ON a.id = t.account_id"
            " LEFT JOIN accounts ta ON ta.id = t.to_account_id"
            " LEFT JOIN categories c ON c.id = t.category_id"
            + where,
            tuple(params),
        ).fetchone()
        return int(row[0])

    def recent_transactions(self, limit: int = 5) -> list[Transaction]:
        rows = self.conn.execute(
            _TXN_SELECT + " ORDER BY t.date DESC, t.id DESC LIMIT ?", (limit,)
        ).fetchall()
        return self._hydrate([self._transaction(row) for row in rows])

    def get_transaction(self, transaction_id: int) -> Transaction:
        row = self.conn.execute(
            _TXN_SELECT + " WHERE t.id = ?", (transaction_id,)
        ).fetchone()
        if not row:
            raise ValueError("记录不存在")
        return self._hydrate([self._transaction(row)])[0]

    def _validate_txn(
        self,
        *,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None,
        to_account_id: int | None,
        currency: str = "CNY",
    ) -> None:
        if kind not in KIND_LABELS:
            raise ValueError("收支类型无效")
        if currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("金额必须大于 0")
        if amount > MAX_AMOUNT_CENTS:
            raise ValueError("金额超出可记录范围")
        account = self.get_account(account_id, include_archived=True)
        if account.archived:
            raise ValueError("该账户已归档，请选择其他账户")
        if kind == "transfer":
            if not to_account_id:
                raise ValueError("请选择转入账户")
            if to_account_id == account_id:
                raise ValueError("转入与转出账户不能相同")
            target = self.get_account(to_account_id, include_archived=True)
            if target.archived:
                raise ValueError("转入账户已归档")
            if category_id is not None:
                raise ValueError("转账不需要分类")
        else:
            if not category_id:
                raise ValueError("请选择分类")
            category = self.get_category(category_id)
            if category.kind != kind:
                raise ValueError("分类与收支类型不匹配")
            if to_account_id is not None:
                raise ValueError("只有转账可以指定转入账户")

    def _converted(self, amount: int, source: str, target: str, day: str) -> int:
        if source == target:
            return int(amount)
        try:
            value = self.rates.convert(amount, source, target, day)
        except RateError as exc:
            raise ValueError(str(exc)) from None
        if value <= 0:
            raise ValueError("按当前汇率折算后的金额过小")
        if value > MAX_AMOUNT_CENTS:
            raise ValueError("折算后的金额超出可记录范围")
        return value

    def _normalize_splits(
        self,
        kind: str,
        amount: int,
        splits: Iterable[tuple[int, int, str]] | None,
    ) -> list[tuple[int, int, str]]:
        if not splits:
            return []
        if kind == "transfer":
            raise ValueError("转账不能拆分")
        result: list[tuple[int, int, str]] = []
        total = 0
        for category_id, split_amount, note in splits:
            category = self.get_category(int(category_id))
            if category is None or category.kind != kind:
                raise ValueError("拆分分类与收支类型不匹配")
            value = int(split_amount)
            if value <= 0:
                raise ValueError("拆分金额必须大于 0")
            total += value
            result.append(
                (category.id, value, str(note or "").strip()[:100])
            )
        if total != int(amount):
            raise ValueError("拆分金额合计必须等于交易金额")
        return result

    @staticmethod
    def _normalize_tags(tags: Iterable[str] | None) -> list[str]:
        if not tags:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for raw in tags:
            name = str(raw or "").strip()[:20]
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            result.append(name)
            if len(result) >= 20:
                break
        return result

    def _replace_splits(
        self, transaction_id: int, splits: list[tuple[int, int, str]]
    ) -> None:
        self.conn.execute(
            "DELETE FROM transaction_splits WHERE transaction_id = ?",
            (transaction_id,),
        )
        for position, (category_id, split_amount, note) in enumerate(splits):
            self.conn.execute(
                "INSERT INTO transaction_splits"
                " (transaction_id, category_id, amount, note, position)"
                " VALUES (?, ?, ?, ?, ?)",
                (transaction_id, category_id, split_amount, note, position),
            )

    def _replace_tags(self, transaction_id: int, tags: list[str]) -> None:
        self.conn.execute(
            "DELETE FROM transaction_tags WHERE transaction_id = ?",
            (transaction_id,),
        )
        for name in tags:
            row = self.conn.execute(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            if row:
                tag_id = int(row["id"])
            else:
                cursor = self.conn.execute(
                    "INSERT INTO tags (name, color, created_at) VALUES (?, ?, ?)",
                    (name, "#5B8DEF", now_iso()),
                )
                tag_id = int(cursor.lastrowid)
            self.conn.execute(
                "INSERT OR IGNORE INTO transaction_tags (transaction_id, tag_id)"
                " VALUES (?, ?)",
                (transaction_id, tag_id),
            )

    def _save_metadata(
        self,
        transaction_id: int,
        splits: list[tuple[int, int, str]],
        tags: list[str],
    ) -> None:
        self._replace_splits(transaction_id, splits)
        self._replace_tags(transaction_id, tags)

    # -------------------------------------------------------- undo snapshots
    UNDO_LIMIT = 100

    _TXN_COLUMNS = (
        "id",
        "date",
        "kind",
        "amount",
        "category_id",
        "account_id",
        "to_account_id",
        "payee",
        "note",
        "created_at",
        "updated_at",
        "currency",
        "account_amount",
        "to_amount",
        "fee",
        "fee_waived",
        "fee_included",
        "recurring_id",
        "import_hash",
        "refund_of_id",
    )

    def _snapshot(self, transaction_id: int) -> dict[str, object]:
        """Full row plus metadata, used by the generic undo log."""
        row = self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if row is None:
            raise ValueError("记录不存在")
        data: dict[str, object] = {
            key: row[key] for key in self._TXN_COLUMNS if key in row.keys()
        }
        data["splits"] = [
            {
                "category_id": int(item["category_id"]),
                "amount": int(item["amount"]),
                "note": item["note"] or "",
                "position": int(item["position"]),
            }
            for item in self.conn.execute(
                "SELECT category_id, amount, note, position FROM transaction_splits"
                " WHERE transaction_id = ? ORDER BY position, id",
                (transaction_id,),
            )
        ]
        data["tags"] = [
            str(item["name"])
            for item in self.conn.execute(
                "SELECT t.name FROM tags t JOIN transaction_tags tt ON tt.tag_id = t.id"
                " WHERE tt.transaction_id = ? ORDER BY t.name",
                (transaction_id,),
            )
        ]
        data["attachments"] = [
            {
                "filename": item["filename"],
                "stored_name": item["stored_name"],
                "mime_type": item["mime_type"] or "",
                "size": int(item["size"] or 0),
                "created_at": item["created_at"] or "",
            }
            for item in self.conn.execute(
                "SELECT filename, stored_name, mime_type, size, created_at"
                " FROM attachments WHERE transaction_id = ? ORDER BY created_at, id",
                (transaction_id,),
            )
        ]
        return data

    def _log_undo(
        self, conn: sqlite3.Connection, action: str, payload: object
    ) -> None:
        conn.execute(
            "INSERT INTO undo_log (action, payload, created_at) VALUES (?, ?, ?)",
            (
                action,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                now_iso(),
            ),
        )
        conn.execute(
            "DELETE FROM undo_log WHERE id NOT IN"
            " (SELECT id FROM undo_log ORDER BY id DESC LIMIT ?)",
            (self.UNDO_LIMIT,),
        )

    def _restore_snapshot(
        self, conn: sqlite3.Connection, data: dict[str, object]
    ) -> None:
        transaction_id = int(data["id"])
        values = [data.get(column) for column in self._TXN_COLUMNS]
        exists = conn.execute(
            "SELECT 1 FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if exists:
            assignments = ", ".join(
                f"{column} = ?" for column in self._TXN_COLUMNS if column != "id"
            )
            conn.execute(
                f"UPDATE transactions SET {assignments} WHERE id = ?",
                (*values[1:], transaction_id),
            )
        else:
            placeholders = ", ".join("?" for _ in self._TXN_COLUMNS)
            conn.execute(
                f"INSERT INTO transactions ({', '.join(self._TXN_COLUMNS)})"
                f" VALUES ({placeholders})",
                values,
            )
        conn.execute(
            "DELETE FROM transaction_splits WHERE transaction_id = ?",
            (transaction_id,),
        )
        for item in data.get("splits", []):  # type: ignore[union-attr]
            conn.execute(
                "INSERT INTO transaction_splits"
                " (transaction_id, category_id, amount, note, position)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    int(item["category_id"]),
                    int(item["amount"]),
                    str(item.get("note") or "")[:100],
                    int(item.get("position") or 0),
                ),
            )
        self._replace_tags(transaction_id, [str(name) for name in data.get("tags", [])])  # type: ignore[union-attr]
        conn.execute(
            "DELETE FROM attachments WHERE transaction_id = ?", (transaction_id,)
        )
        for item in data.get("attachments", []):  # type: ignore[union-attr]
            conn.execute(
                "INSERT INTO attachments"
                " (transaction_id, filename, stored_name, mime_type, size, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    str(item["filename"]),
                    str(item["stored_name"]),
                    str(item.get("mime_type") or ""),
                    int(item.get("size") or 0),
                    str(item.get("created_at") or now_iso()),
                ),
            )

    def _refunded_ids(self, transaction_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE refund_of_id = ?",
            (transaction_id,),
        ).fetchone()
        return int(row[0])

    def _refund_total(self, refund_of_id: int, exclude_id: int | None = None) -> int:
        clause = " AND id <> ?" if exclude_id is not None else ""
        params: tuple[object, ...] = (refund_of_id,)
        if exclude_id is not None:
            params = (refund_of_id, exclude_id)
        rows = self.conn.execute(
            "SELECT amount, currency, date FROM transactions"
            " WHERE refund_of_id = ?" + clause,
            params,
        ).fetchall()
        return sum(
            self._to_base(int(row["amount"]), row["currency"], row["date"])
            for row in rows
        )

    def _validate_refund(
        self,
        *,
        kind: str,
        amount: int,
        currency: str,
        refund_of_id: int | None,
        transaction_id: int | None = None,
        date: str | None = None,
    ) -> None:
        if refund_of_id is None:
            return
        if kind != "income":
            raise ValueError("只有收入记录可以关联退款")
        if transaction_id is not None and int(refund_of_id) == int(transaction_id):
            raise ValueError("退款不能关联到自身")
        row = self.conn.execute(
            "SELECT id, kind, amount, currency, date FROM transactions WHERE id = ?",
            (int(refund_of_id),),
        ).fetchone()
        if row is None:
            raise ValueError("关联的原支出不存在")
        if row["kind"] != "expense":
            raise ValueError("退款只能关联支出记录")
        original = self._to_base(
            int(row["amount"]), row["currency"], row["date"]
        )
        previous = self._refund_total(
            int(refund_of_id), exclude_id=transaction_id
        )
        current = self._to_base(int(amount), currency, date or today_iso())
        if previous + current > original:
            raise ValueError("退款金额合计不能超过原支出")

    def add_transaction(
        self,
        *,
        date: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        currency: str = "CNY",
        account_amount: int | None = None,
        to_amount: int | None = None,
        fee_waived: bool = False,
        fee_included: bool | None = None,
        recurring_id: int | None = None,
        refund_of_id: int | None = None,
        splits: Iterable[tuple[int, int, str]] | None = None,
        tags: Iterable[str] | None = None,
        import_hash: str | None = None,
    ) -> int:
        date = normalize_day(date)
        self._validate_txn(
            kind=kind,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            currency=currency,
        )
        self._validate_refund(
            kind=kind,
            amount=amount,
            currency=currency,
            refund_of_id=refund_of_id,
            date=date,
        )
        split_rows = self._normalize_splits(kind, amount, splits)
        tag_names = self._normalize_tags(tags)
        account = self.get_account(account_id, include_archived=True)
        posted = (
            self._converted(amount, currency, account.currency, date)
            if account_amount is None
            else int(account_amount)
        )
        if posted <= 0:
            raise ValueError("账户记账金额必须大于 0")
        received = 0
        fee = 0
        included = False
        if kind == "transfer":
            target = self.get_account(to_account_id, include_archived=True)
            received = (
                self._converted(amount, currency, target.currency, date)
                if to_amount is None
                else int(to_amount)
            )
            if received <= 0:
                raise ValueError("到账金额必须大于 0")
            fee, included, received = self._apply_transfer_fee(
                account=account,
                posted=posted,
                received=received,
                date=date,
                currency=currency,
                target_currency=target.currency,
                fee_waived=bool(fee_waived),
                fee_included=fee_included,
            )
        cursor = self.conn.execute(
            "INSERT INTO transactions (date, kind, amount, currency, account_amount,"
            " to_amount, fee, fee_waived, fee_included, recurring_id, refund_of_id,"
            " category_id, account_id, to_account_id, payee, note, import_hash,"
            " created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date,
                kind,
                amount,
                currency,
                posted,
                received,
                fee,
                int(bool(fee_waived)),
                int(included),
                recurring_id,
                refund_of_id,
                category_id,
                account_id,
                to_account_id,
                str(payee or "").strip()[:60],
                str(note or "").strip()[:200],
                str(import_hash or "") or None,
                now_iso(),
            ),
        )
        transaction_id = int(cursor.lastrowid)
        self._save_metadata(transaction_id, split_rows, tag_names)
        self.conn.commit()
        snapshot = self._snapshot(transaction_id)
        with self.db.transaction() as conn:
            self._log_undo(conn, "add", snapshot)
        return transaction_id

    def update_transaction(
        self,
        transaction_id: int,
        *,
        date: str,
        kind: str,
        amount: int,
        account_id: int,
        category_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
        currency: str = "CNY",
        account_amount: int | None = None,
        to_amount: int | None = None,
        fee_waived: bool = False,
        fee_included: bool | None = None,
        refund_of_id: int | None = None,
        splits: Iterable[tuple[int, int, str]] | None = None,
        tags: Iterable[str] | None = None,
    ) -> None:
        previous = self._snapshot(transaction_id)
        self.get_transaction(transaction_id)
        date = normalize_day(date)
        self._validate_txn(
            kind=kind,
            amount=amount,
            account_id=account_id,
            category_id=category_id,
            to_account_id=to_account_id,
            currency=currency,
        )
        self._validate_refund(
            kind=kind,
            amount=amount,
            currency=currency,
            refund_of_id=refund_of_id,
            transaction_id=transaction_id,
            date=date,
        )
        if kind != "expense" and self._refunded_ids(transaction_id):
            raise ValueError("该支出已有退款记录，不能改为其他类型")
        if kind == "expense" and self._refunded_ids(transaction_id):
            refunded = self._refund_total(transaction_id)
            if self._to_base(amount, currency, date) < refunded:
                raise ValueError("原支出金额不能小于已退款金额")
        split_rows = (
            self._normalize_splits(kind, amount, splits) if splits is not None else None
        )
        tag_names = (
            self._normalize_tags(tags) if tags is not None else None
        )
        account = self.get_account(account_id, include_archived=True)
        posted = (
            self._converted(amount, currency, account.currency, date)
            if account_amount is None
            else int(account_amount)
        )
        if posted <= 0:
            raise ValueError("账户记账金额必须大于 0")
        received = 0
        fee = 0
        included = False
        if kind == "transfer":
            target = self.get_account(to_account_id, include_archived=True)
            received = (
                self._converted(amount, currency, target.currency, date)
                if to_amount is None
                else int(to_amount)
            )
            if received <= 0:
                raise ValueError("到账金额必须大于 0")
            fee, included, received = self._apply_transfer_fee(
                account=account,
                posted=posted,
                received=received,
                date=date,
                currency=currency,
                target_currency=target.currency,
                fee_waived=bool(fee_waived),
                fee_included=fee_included,
                exclude_transaction_id=transaction_id,
            )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE transactions SET date = ?, kind = ?, amount = ?, currency = ?,"
                " account_amount = ?, to_amount = ?, fee = ?, fee_waived = ?,"
                " fee_included = ?, refund_of_id = ?, category_id = ?, account_id = ?,"
                " to_account_id = ?, payee = ?, note = ?, updated_at = ? WHERE id = ?",
                (
                    date,
                    kind,
                    amount,
                    currency,
                    posted,
                    received,
                    fee,
                    int(bool(fee_waived)),
                    int(included),
                    refund_of_id,
                    category_id,
                    account_id,
                    to_account_id,
                    str(payee or "").strip()[:60],
                    str(note or "").strip()[:200],
                    now_iso(),
                    transaction_id,
                ),
            )
            if split_rows is not None:
                self._replace_splits(transaction_id, split_rows)
            if tag_names is not None:
                self._replace_tags(transaction_id, tag_names)
            self._log_undo(conn, "update", previous)

    def delete_transaction(self, transaction_id: int) -> None:
        if self._refunded_ids(transaction_id):
            raise ValueError("该交易已有退款记录，请先删除退款")
        snapshot = self._snapshot(transaction_id)
        with self.db.transaction() as conn:
            self._log_undo(conn, "delete", snapshot)
            conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    def set_transaction_metadata(
        self,
        transaction_id: int,
        *,
        splits: list[tuple[int, int, str]] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        transaction = self.get_transaction(transaction_id)
        split_rows = (
            self._normalize_splits(transaction.kind, transaction.amount, splits)
            if splits is not None
            else None
        )
        tag_names = self._normalize_tags(tags) if tags is not None else None
        previous = self._snapshot(transaction_id)
        with self.db.transaction() as conn:
            if split_rows is not None:
                self._replace_splits(transaction_id, split_rows)
            if tag_names is not None:
                self._replace_tags(transaction_id, tag_names)
            self._log_undo(conn, "metadata", previous)

    # ----------------------------------------------------------- bulk & undo
    def bulk_update_transactions(
        self,
        transaction_ids: Iterable[int],
        *,
        category_id: int | None = None,
        add_tags: Iterable[str] | None = None,
        remove_tags: Iterable[str] | None = None,
    ) -> int:
        """Update category/tags for many rows and remember how to undo it."""
        ids = sorted({int(item) for item in transaction_ids})
        if not ids:
            return 0
        add_names = self._normalize_tags(add_tags)
        remove_names = {name.casefold() for name in self._normalize_tags(remove_tags)}
        if category_id is None and not add_names and not remove_names:
            return 0
        category = self.get_category(category_id) if category_id is not None else None
        placeholders = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT id, kind, category_id FROM transactions WHERE id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
        if not rows:
            return 0
        previous: list[dict[str, object]] = []
        for row in rows:
            split_count = self.conn.execute(
                "SELECT COUNT(*) FROM transaction_splits WHERE transaction_id = ?",
                (row["id"],),
            ).fetchone()[0]
            if row["kind"] == "transfer":
                continue
            if category is not None:
                if row["kind"] != category.kind:
                    continue
                if split_count:
                    # Changing the primary category of a split transaction
                    # would leave the splits pointing at another category.
                    continue
            tag_rows = self.conn.execute(
                "SELECT t.name FROM tags t"
                " JOIN transaction_tags tt ON tt.tag_id = t.id"
                " WHERE tt.transaction_id = ? ORDER BY t.name",
                (row["id"],),
            ).fetchall()
            previous.append(
                {
                    "id": int(row["id"]),
                    "category_id": row["category_id"],
                    "tags": [tag["name"] for tag in tag_rows],
                }
            )
        if not previous:
            return 0
        with self.db.transaction() as conn:
            for item in previous:
                transaction_id = int(item["id"])
                if category_id is not None:
                    conn.execute(
                        "UPDATE transactions SET category_id = ?, updated_at = ?"
                        " WHERE id = ?",
                        (category_id, now_iso(), transaction_id),
                    )
                if add_names or remove_names:
                    current = [
                        str(tag["name"])
                        for tag in conn.execute(
                            "SELECT t.name FROM tags t"
                            " JOIN transaction_tags tt ON tt.tag_id = t.id"
                            " WHERE tt.transaction_id = ?",
                            (transaction_id,),
                        )
                    ]
                    next_names = [
                        name for name in current if name.casefold() not in remove_names
                    ]
                    known = {name.casefold() for name in next_names}
                    for name in add_names:
                        if name.casefold() not in known:
                            next_names.append(name)
                            known.add(name.casefold())
                    self._replace_tags(transaction_id, next_names)
            conn.execute(
                "INSERT INTO undo_log (action, payload, created_at) VALUES (?, ?, ?)",
                (
                    "bulk_update",
                    json.dumps(previous, ensure_ascii=False, separators=(",", ":")),
                    now_iso(),
                ),
            )
        return len(previous)

    def has_undo(self) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM undo_log LIMIT 1").fetchone())

    def undo_last(self) -> str:
        row = self.conn.execute(
            "SELECT id, action, payload FROM undo_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return ""
        action = str(row["action"])
        payload = json.loads(row["payload"])
        with self.db.transaction() as conn:
            if action == "add":
                transaction_id = int(payload["id"])
                if self._refunded_ids(transaction_id):
                    raise ValueError("这笔记录已有关联退款，无法撤销新增")
                conn.execute(
                    "DELETE FROM transactions WHERE id = ?", (transaction_id,)
                )
            elif action in ("update", "delete", "metadata"):
                self._restore_snapshot(conn, payload)
            else:
                # Legacy (and current) bulk edits store a list of row states.
                for item in payload:
                    conn.execute(
                        "UPDATE transactions SET category_id = ?, updated_at = ?"
                        " WHERE id = ?",
                        (item.get("category_id"), now_iso(), int(item["id"])),
                    )
                    self._replace_tags(
                        int(item["id"]),
                        [str(name) for name in item.get("tags", [])],
                    )
            conn.execute("DELETE FROM undo_log WHERE id = ?", (row["id"],))
        messages = {
            "add": "已撤销新增交易",
            "update": "已撤销修改",
            "delete": "已恢复删除的交易",
            "metadata": "已撤销标签/拆分修改",
        }
        if action == "bulk_update":
            return f"已撤销 {len(payload)} 笔批量修改"
        return messages.get(action, "已撤销上一步操作")

    # ------------------------------------------------------- tags & attachments
    def tags(self) -> list[Tag]:
        return [
            Tag(int(row["id"]), row["name"], row["color"] or "#5B8DEF")
            for row in self.conn.execute(
                "SELECT id, name, color FROM tags ORDER BY name"
            )
        ]

    def attachments(self, transaction_id: int) -> list[Attachment]:
        return [
            Attachment(
                id=int(row["id"]),
                transaction_id=int(row["transaction_id"]),
                filename=row["filename"],
                stored_name=row["stored_name"],
                mime_type=row["mime_type"] or "",
                size=int(row["size"] or 0),
                created_at=row["created_at"] or "",
            )
            for row in self.conn.execute(
                "SELECT * FROM attachments WHERE transaction_id = ?"
                " ORDER BY created_at, id",
                (transaction_id,),
            )
        ]

    def get_attachment(self, attachment_id: int) -> Attachment:
        row = self.conn.execute(
            "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        if not row:
            raise ValueError("附件不存在")
        return Attachment(
            id=int(row["id"]),
            transaction_id=int(row["transaction_id"]),
            filename=row["filename"],
            stored_name=row["stored_name"],
            mime_type=row["mime_type"] or "",
            size=int(row["size"] or 0),
            created_at=row["created_at"] or "",
        )

    def add_attachment(
        self,
        transaction_id: int,
        *,
        filename: str,
        stored_name: str,
        mime_type: str = "",
        size: int = 0,
    ) -> int:
        self.get_transaction(transaction_id)
        cursor = self.conn.execute(
            "INSERT INTO attachments"
            " (transaction_id, filename, stored_name, mime_type, size, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                transaction_id,
                str(filename)[:255],
                str(stored_name)[:255],
                str(mime_type)[:100],
                int(size),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def delete_attachment(self, attachment_id: int) -> Attachment:
        attachment = self.get_attachment(attachment_id)
        self.conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        self.conn.commit()
        return attachment

    # ----------------------------------------------------------- CSV import rules
    def csv_rules(self) -> list[CsvRule]:
        return [
            self._csv_rule(row)
            for row in self.conn.execute(
                "SELECT * FROM csv_import_rules ORDER BY name COLLATE NOCASE"
            )
        ]

    def get_csv_rule(self, rule_id: int) -> CsvRule:
        row = self.conn.execute(
            "SELECT * FROM csv_import_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        if not row:
            raise ValueError("导入规则不存在")
        return self._csv_rule(row)

    @staticmethod
    def _csv_rule(row: sqlite3.Row) -> CsvRule:
        try:
            mapping = json.loads(row["mapping"] or "{}")
        except (TypeError, ValueError):
            mapping = {}
        return CsvRule(
            id=int(row["id"]),
            name=row["name"],
            mapping={str(key): str(value) for key, value in mapping.items()},
            default_kind=row["default_kind"] or "expense",
            default_account_id=(
                int(row["default_account_id"])
                if row["default_account_id"] is not None
                else None
            ),
            default_category_id=(
                int(row["default_category_id"])
                if row["default_category_id"] is not None
                else None
            ),
            dedup=bool(row["dedup"]),
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def add_csv_rule(
        self,
        name: str,
        *,
        mapping: dict[str, str],
        default_kind: str = "expense",
        default_account_id: int | None = None,
        default_category_id: int | None = None,
        dedup: bool = True,
    ) -> int:
        name = str(name or "").strip()[:60]
        if not name:
            raise ValueError("规则名称不能为空")
        try:
            cursor = self.conn.execute(
                "INSERT INTO csv_import_rules"
                " (name, mapping, default_kind, default_account_id,"
                " default_category_id, dedup, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    json.dumps(mapping, ensure_ascii=False),
                    default_kind,
                    default_account_id,
                    default_category_id,
                    int(bool(dedup)),
                    now_iso(),
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("同名导入规则已存在") from None
        self.conn.commit()
        return int(cursor.lastrowid)

    def update_csv_rule(
        self,
        rule_id: int,
        *,
        name: str,
        mapping: dict[str, str],
        default_kind: str = "expense",
        default_account_id: int | None = None,
        default_category_id: int | None = None,
        dedup: bool = True,
    ) -> None:
        name = str(name or "").strip()[:60]
        if not name:
            raise ValueError("规则名称不能为空")
        try:
            self.conn.execute(
                "UPDATE csv_import_rules SET name = ?, mapping = ?,"
                " default_kind = ?, default_account_id = ?, default_category_id = ?,"
                " dedup = ?, updated_at = ? WHERE id = ?",
                (
                    name,
                    json.dumps(mapping, ensure_ascii=False),
                    default_kind,
                    default_account_id,
                    default_category_id,
                    int(bool(dedup)),
                    now_iso(),
                    rule_id,
                ),
            )
        except sqlite3.IntegrityError:
            raise ValueError("同名导入规则已存在") from None
        self.conn.commit()

    def delete_csv_rule(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM csv_import_rules WHERE id = ?", (rule_id,))
        self.conn.commit()

    def import_hash_exists(self, import_hash: str) -> bool:
        if not import_hash:
            return False
        return (
            self.conn.execute(
                "SELECT 1 FROM transactions WHERE import_hash = ?", (import_hash,)
            ).fetchone()
            is not None
        )

    def transaction_matches(
        self,
        *,
        date: str,
        kind: str,
        amount: int,
        currency: str,
        account_id: int,
        to_account_id: int | None,
        payee: str,
    ) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM transactions WHERE date = ? AND kind = ?"
                " AND amount = ? AND currency = ? AND account_id = ?"
                " AND COALESCE(to_account_id, 0) = ?"
                " AND lower(trim(payee)) = lower(trim(?))",
                (
                    date,
                    kind,
                    int(amount),
                    currency.upper(),
                    int(account_id),
                    int(to_account_id or 0),
                    payee or "",
                ),
            ).fetchone()
            is not None
        )

    # -------------------------------------------------------------- analytics
    def _to_base(self, amount: int, currency: str, day: str | None = None) -> int:
        if currency == self.base_currency:
            return int(amount)
        try:
            return self.rates.convert(amount, currency, self.base_currency, day)
        except RateError as exc:
            raise ValueError(str(exc)) from None

    def month_stats(self, month: str | None = None) -> MonthStats:
        month = month or month_of(today())
        start, end = month_bounds(month)
        rows = self.conn.execute(
            "SELECT t.kind, t.amount, t.currency, t.date, t.fee, t.refund_of_id,"
            "       a.currency AS account_currency"
            " FROM transactions t JOIN accounts a ON a.id = t.account_id"
            " WHERE t.date >= ? AND t.date < ?"
            " AND (t.kind IN ('expense','income') OR (t.kind = 'transfer' AND t.fee > 0))",
            (start, end),
        ).fetchall()
        totals = {"income": 0, "expense": 0}
        for row in rows:
            if row["kind"] == "transfer":
                totals["expense"] += self._to_base(
                    int(row["fee"]), row["account_currency"], row["date"]
                )
                continue
            value = self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
            if row["kind"] == "income" and row["refund_of_id"] is not None:
                totals["expense"] -= value
            else:
                totals[row["kind"]] += value
        return MonthStats(
            month=month, income=totals["income"], expense=totals["expense"]
        )

    def transactions_between(self, start_date: str, end_date: str) -> list[Transaction]:
        """All transactions in an inclusive ISO date range, hydrated."""
        start = normalize_day(start_date)
        end = normalize_day(end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        return self.transactions(
            TransactionFilter(start_date=start, end_date=end, limit=100_000)
        )

    def _range_totals(self, start: str, end: str) -> tuple[int, int]:
        totals = {"income": 0, "expense": 0}
        for txn in self.transactions_between(start, end):
            if txn.kind == "transfer":
                if txn.fee > 0:
                    totals["expense"] += self._to_base(
                        txn.fee, txn.account_currency, txn.date
                    )
                continue
            value = self._to_base(txn.amount, txn.currency, txn.date)
            if txn.kind == "income" and txn.refund_of_id is not None:
                totals["expense"] -= value
            else:
                totals[txn.kind] += value
        return totals["income"], totals["expense"]

    def range_report(
        self, start_date: str, end_date: str, dimension: str = "category"
    ) -> RangeReport:
        """Totals, period comparisons and a dimension breakdown for a range."""
        if dimension not in ("category", "tag", "account"):
            raise ValueError("不支持的报表维度")
        start = normalize_day(start_date)
        end = normalize_day(end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        first = date_cls.fromisoformat(start)
        last = date_cls.fromisoformat(end)
        span = (last - first).days + 1

        rows = self.transactions_between(start, end)
        income = 0
        expense = 0
        monthly: dict[str, dict[str, int]] = {}
        buckets: dict[tuple[object, str, str], int] = {}
        palette = ("#3D6DF2", "#12B76A", "#F79009", "#7A5AF8", "#E5484D", "#06AED4")
        refund_cache: dict[int, Transaction] = {}

        def add_bucket(key: object, name: str, color: str, amount: int) -> None:
            if not amount:
                return
            bucket_key = (key, name, color)
            buckets[bucket_key] = buckets.get(bucket_key, 0) + amount

        def original(txn: Transaction) -> Transaction | None:
            if not txn.refund_of_id:
                return None
            if txn.refund_of_id not in refund_cache:
                try:
                    refund_cache[txn.refund_of_id] = self.get_transaction(txn.refund_of_id)
                except ValueError:
                    return None
            return refund_cache[txn.refund_of_id]

        def apply_month(txn: Transaction, kind: str, value: int) -> None:
            month = txn.date[:7]
            slot = monthly.setdefault(month, {"income": 0, "expense": 0})
            slot[kind] += value

        def apply_breakdown(txn: Transaction, amount: int) -> None:
            if dimension == "category":
                if txn.splits:
                    for split in txn.splits:
                        share = self._to_base(split.amount, txn.currency, txn.date)
                        add_bucket(
                            split.category_id,
                            split.category_name,
                            split.category_color,
                            share if amount > 0 else -share,
                        )
                else:
                    add_bucket(
                        txn.category_id or 0,
                        txn.category_name or "未分类",
                        txn.category_color or palette[0],
                        amount,
                    )
            elif dimension == "tag":
                if txn.tags:
                    for tag in txn.tags:
                        add_bucket(tag.id, tag.name, tag.color or palette[1], amount)
                elif amount > 0:
                    add_bucket(0, "未标签", palette[5], amount)
            else:
                add_bucket(
                    txn.account_id,
                    txn.account_name,
                    palette[txn.account_id % len(palette)],
                    amount,
                )

        for txn in rows:
            if txn.kind == "transfer":
                if txn.fee > 0:
                    fee = self._to_base(txn.fee, txn.account_currency, txn.date)
                    expense += fee
                    apply_month(txn, "expense", fee)
                    add_bucket(-1, "提现手续费", "#E5484D", fee)
                continue
            value = self._to_base(txn.amount, txn.currency, txn.date)
            if txn.kind == "income" and txn.refund_of_id is not None:
                expense -= value
                apply_month(txn, "expense", -value)
                parent = original(txn)
                if parent is not None:
                    apply_breakdown(parent, -value)
                else:
                    add_bucket(-2, "退款", "#667085", -value)
            else:
                if txn.kind == "income":
                    income += value
                    apply_month(txn, "income", value)
                else:
                    expense += value
                    apply_month(txn, "expense", value)
                    apply_breakdown(txn, value)

        previous_end = first - timedelta(days=1)
        previous_start = previous_end - timedelta(days=span - 1)
        try:
            year_start = first.replace(year=first.year - 1)
        except ValueError:
            year_start = first.replace(year=first.year - 1, day=28)
        try:
            year_end = last.replace(year=last.year - 1)
        except ValueError:
            year_end = last.replace(year=last.year - 1, day=28)
        previous_income, previous_expense = self._range_totals(
            previous_start.isoformat(), previous_end.isoformat()
        )
        year_income, year_expense = self._range_totals(
            year_start.isoformat(), year_end.isoformat()
        )

        breakdown = [
            CategorySpend(category_id=int(key), name=name, color=color, amount=amount)
            for (key, name, color), amount in buckets.items()
            if amount > 0
        ]
        breakdown.sort(key=lambda item: (-item.amount, item.name))
        trend = tuple(
            MonthStats(month=month, income=values["income"], expense=values["expense"])
            for month, values in sorted(monthly.items())
        )
        return RangeReport(
            start_date=start,
            end_date=end,
            income=income,
            expense=expense,
            previous_income=previous_income,
            previous_expense=previous_expense,
            year_income=year_income,
            year_expense=year_expense,
            breakdown=tuple(breakdown),
            trend=trend,
        )

    def net_worth(self) -> NetWorth:
        accounts = self.accounts(include_archived=False)
        account_assets = 0
        liabilities = 0
        for account in accounts:
            value = self._to_base(account.balance, account.currency)
            if account.group == "liability":
                # Liability accounts hold their face value; accepting a positive
                # opening balance must not silently turn debt into an asset.
                liabilities += abs(value)
            else:
                account_assets += value
        fixed = self.fixed_assets()
        fixed_total = self.fixed_asset_value()
        return NetWorth(
            account_assets=account_assets,
            liabilities=liabilities,
            fixed_assets=fixed_total,
            fixed_asset_count=len(fixed),
            asset_accounts=sum(1 for account in accounts if account.group == "asset"),
            liability_accounts=sum(1 for account in accounts if account.group == "liability"),
        )

    def net_worth_history(
        self, months: int = 12, end_month: str | None = None
    ) -> list[NetWorthPoint]:
        """Month-end net worth reconstructed from account flows and valuations."""
        months = max(1, min(int(months), 60))
        end_month = end_month or month_of(today())
        labels = recent_months(months, end_month)
        accounts = self.accounts(include_archived=True)
        points: list[NetWorthPoint] = []
        for label in labels:
            if label == end_month:
                current = self.net_worth()
                assets = current.account_assets + current.fixed_assets
                liabilities = current.liabilities
                points.append(
                    NetWorthPoint(
                        month=label,
                        assets=assets,
                        liabilities=liabilities,
                        net=assets - liabilities,
                    )
                )
                continue
            _, exclusive_end = month_bounds(label)
            last_day = (
                date_cls.fromisoformat(exclusive_end) - timedelta(days=1)
            ).isoformat()
            assets = 0
            liabilities = 0
            for account in accounts:
                value = self._to_base(
                    self.account_balance_at(account.id, last_day),
                    account.currency,
                    last_day,
                )
                if account.group == "liability":
                    liabilities += abs(value)
                else:
                    assets += value
            assets += self.fixed_asset_value_at(last_day)
            points.append(
                NetWorthPoint(
                    month=label,
                    assets=assets,
                    liabilities=liabilities,
                    net=assets - liabilities,
                )
            )
        return points

    def cash_flow_forecast(
        self, months: int = 6, start_month: str | None = None
    ) -> list[ForecastPoint]:
        """Project recurring items plus the 3-month non-recurring average.

        Only cash/debit accounts fund the starting balance; transfers are not
        counted because they usually move money between the user's own accounts.
        """
        months = max(1, min(int(months), 24))
        if start_month:
            month_bounds(start_month)
            start = start_month
        else:
            start = shift_month(month_of(today()), 1)
        labels = [shift_month(start, index) for index in range(months)]
        last_month = labels[-1]
        _, horizon_end = month_bounds(last_month)
        start_cash = sum(
            self._to_base(account.balance, account.currency)
            for account in self.accounts()
            if account.type in ("cash", "debit")
        )

        history_end, _ = month_bounds(month_of(today()))
        history_start, _ = month_bounds(shift_month(month_of(today()), -3))
        rows = self.conn.execute(
            "SELECT t.kind, t.amount, t.currency, t.date, t.refund_of_id"
            " FROM transactions t"
            " WHERE t.date >= ? AND t.date < ? AND t.recurring_id IS NULL"
            " AND t.kind IN ('income','expense')",
            (history_start, history_end),
        ).fetchall()
        average = {"income": 0, "expense": 0}
        for row in rows:
            value = self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
            if row["kind"] == "income" and row["refund_of_id"] is not None:
                average["expense"] -= value
            else:
                average[row["kind"]] += value
        for key in average:
            average[key] = int(round(average[key] / 3))

        recurring = {"income": {}, "expense": {}}
        for rule in self.recurring_rules(active_only=True):
            if rule.kind not in recurring:
                continue
            cursor = rule.next_date
            for _ in range(2000):
                if cursor > horizon_end:
                    break
                if rule.end_date and cursor > rule.end_date:
                    break
                if cursor[:7] >= start:
                    recurring[rule.kind][cursor[:7]] = recurring[rule.kind].get(
                        cursor[:7], 0
                    ) + self._to_base(rule.amount, rule.currency, cursor)
                cursor = next_recurring_date(
                    cursor, rule.frequency, rule.interval_count
                )

        points: list[ForecastPoint] = []
        planned = {"income": {}, "expense": {}}
        for item in self.planned_transactions(status="planned"):
            if item.kind not in planned or item.date < start or item.date >= horizon_end:
                continue
            month = item.date[:7]
            planned[item.kind][month] = planned[item.kind].get(month, 0) + self._to_base(
                item.amount, item.currency, item.date
            )
        cash = start_cash
        for month in labels:
            income = (
                average["income"]
                + recurring["income"].get(month, 0)
                + planned["income"].get(month, 0)
            )
            expense = (
                average["expense"]
                + recurring["expense"].get(month, 0)
                + planned["expense"].get(month, 0)
            )
            net = income - expense
            cash += net
            points.append(
                ForecastPoint(
                    month=month, income=income, expense=expense, net=net, ending_cash=cash
                )
            )
        return points

    def liquid_balance(self) -> int:
        return sum(
            self._to_base(account.balance, account.currency)
            for account in self.accounts()
            if account.type in ("cash", "debit")
        )

    def trend(self, months: int = 12, end_month: str | None = None) -> list[MonthStats]:
        months = max(1, min(int(months), 60))
        end_month = end_month or month_of(today())
        labels = recent_months(months, end_month)
        start, _ = month_bounds(labels[0])
        _, end = month_bounds(labels[-1])
        rows = self.conn.execute(
            "SELECT substr(t.date, 1, 7) AS month, t.kind, t.amount, t.currency,"
            "       t.date, t.fee, t.refund_of_id, a.currency AS account_currency"
            " FROM transactions t JOIN accounts a ON a.id = t.account_id"
            " WHERE t.date >= ? AND t.date < ?"
            " AND (t.kind IN ('expense','income') OR (t.kind = 'transfer' AND t.fee > 0))",
            (start, end),
        ).fetchall()
        totals: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = totals.setdefault(row["month"], {"income": 0, "expense": 0})
            if row["kind"] == "transfer":
                bucket["expense"] += self._to_base(
                    int(row["fee"]), row["account_currency"], row["date"]
                )
                continue
            value = self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
            if row["kind"] == "income" and row["refund_of_id"] is not None:
                bucket["expense"] -= value
            else:
                bucket[row["kind"]] += value
        return [
            MonthStats(
                month=month,
                income=totals.get(month, {}).get("income", 0),
                expense=totals.get(month, {}).get("expense", 0),
            )
            for month in labels
        ]

    def category_breakdown(
        self, month: str | None = None, kind: str = "expense"
    ) -> list[CategorySpend]:
        if month:
            start, end = month_bounds(month)
            date_clause = " AND t.date >= ? AND t.date < ?"
            params: tuple = (kind, start, end)
        else:
            date_clause = ""
            params = (kind,)
        refund_filter = " AND t.refund_of_id IS NULL" if kind == "income" else ""
        rows = self.conn.execute(
            "SELECT c.id, c.name, c.color, t.amount, t.currency, t.date"
            " FROM transactions t JOIN categories c ON c.id = t.category_id"
            " WHERE t.kind = ? AND NOT EXISTS (SELECT 1 FROM transaction_splits s"
            " WHERE s.transaction_id = t.id)" + refund_filter + date_clause,
            params,
        ).fetchall()
        split_rows = self.conn.execute(
            "SELECT c.id, c.name, c.color, s.amount, t.currency, t.date"
            " FROM transaction_splits s JOIN transactions t ON t.id = s.transaction_id"
            " JOIN categories c ON c.id = s.category_id"
            " WHERE t.kind = ?" + refund_filter + date_clause,
            params,
        ).fetchall()
        rows = list(rows) + list(split_rows)
        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            item = grouped.setdefault(
                int(row["id"]),
                {
                    "name": row["name"],
                    "color": row["color"],
                    "amount": 0,
                },
            )
            item["amount"] = int(item["amount"]) + self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
        if kind == "expense":
            refund_params: tuple = (start, end) if month else ()
            refund_rows = self.conn.execute(
                "SELECT COALESCE(o.category_id, t.category_id) AS id,"
                "       c.name, c.color, t.amount, t.currency, t.date"
                " FROM transactions t"
                " LEFT JOIN transactions o ON o.id = t.refund_of_id"
                " JOIN categories c ON c.id = COALESCE(o.category_id, t.category_id)"
                " WHERE t.kind = 'income' AND t.refund_of_id IS NOT NULL"
                + date_clause,
                refund_params,
            ).fetchall()
            for row in refund_rows:
                item = grouped.setdefault(
                    int(row["id"]),
                    {"name": row["name"], "color": row["color"], "amount": 0},
                )
                item["amount"] = int(item["amount"]) - self._to_base(
                    int(row["amount"]), row["currency"], row["date"]
                )
        result = [
            CategorySpend(
                category_id=category_id,
                name=str(item["name"]),
                color=str(item["color"]),
                amount=int(item["amount"]),
            )
            for category_id, item in grouped.items()
            if int(item["amount"]) != 0
        ]
        if kind == "expense":
            fee_clause = " AND t.date >= ? AND t.date < ?" if month else ""
            fee_params: tuple = (start, end) if month else ()
            fee_rows = self.conn.execute(
                "SELECT t.fee, a.currency AS account_currency, t.date"
                " FROM transactions t JOIN accounts a ON a.id = t.account_id"
                " WHERE t.kind = 'transfer' AND t.fee > 0" + fee_clause,
                fee_params,
            ).fetchall()
            if fee_rows:
                fee_total = sum(
                    self._to_base(
                        int(row["fee"]), row["account_currency"], row["date"]
                    )
                    for row in fee_rows
                )
                if fee_total:
                    result.append(
                        CategorySpend(
                            category_id=-1,
                            name="提现手续费",
                            color="#E5484D",
                            amount=fee_total,
                        )
                    )
        result.sort(key=lambda item: (-item.amount, item.category_id))
        return result

    def top_payees(self, month: str | None = None, limit: int = 5) -> list[PayeeSpend]:
        params: list[object] = []
        date_clause = ""
        if month:
            start, end = month_bounds(month)
            date_clause = " AND date >= ? AND date < ?"
            params.extend([start, end])
        rows = self.conn.execute(
            "SELECT payee, amount, currency, date FROM transactions"
            " WHERE kind = 'expense' AND payee <> ''" + date_clause,
            tuple(params),
        ).fetchall()
        totals: dict[str, list[int]] = {}
        for row in rows:
            bucket = totals.setdefault(row["payee"], [0, 0])
            bucket[0] += self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
            bucket[1] += 1
        refund_clause = " AND t.date >= ? AND t.date < ?" if month else ""
        refund_params: tuple = (start, end) if month else ()
        refund_rows = self.conn.execute(
            "SELECT COALESCE(o.payee, t.payee) AS payee, t.amount,"
            "       t.currency, t.date"
            " FROM transactions t LEFT JOIN transactions o ON o.id = t.refund_of_id"
            " WHERE t.kind = 'income' AND t.refund_of_id IS NOT NULL"
            " AND COALESCE(o.payee, t.payee) <> ''" + refund_clause,
            refund_params,
        ).fetchall()
        for row in refund_rows:
            bucket = totals.setdefault(row["payee"], [0, 0])
            bucket[0] -= self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
        fee_rows = self.conn.execute(
            "SELECT fee, a.currency AS account_currency, date"
            " FROM transactions t JOIN accounts a ON a.id = t.account_id"
            " WHERE t.kind = 'transfer' AND t.fee > 0" + date_clause,
            tuple(params),
        ).fetchall()
        for row in fee_rows:
            bucket = totals.setdefault("提现手续费", [0, 0])
            bucket[0] += self._to_base(
                int(row["fee"]), row["account_currency"], row["date"]
            )
            bucket[1] += 1
        ordered = sorted(
            ((payee, value) for payee, value in totals.items() if value[0] > 0),
            key=lambda item: (-item[1][0], item[0]),
        )
        return [
            PayeeSpend(payee=payee, amount=value[0], count=value[1])
            for payee, value in ordered[: max(1, min(int(limit), 50))]
        ]

    def largest_expense(self, month: str | None = None) -> Transaction | None:
        params: list[object] = []
        clause = " WHERE t.kind = 'expense'"
        if month:
            start, end = month_bounds(month)
            clause += " AND t.date >= ? AND t.date < ?"
            params.extend([start, end])
        rows = self.conn.execute(
            _TXN_SELECT + clause,
            tuple(params),
        ).fetchall()
        hydrated = self._hydrate([self._transaction(row) for row in rows])
        best: tuple[int, Transaction] | None = None
        for transaction in hydrated:
            value = self._to_base(
                transaction.amount, transaction.currency, transaction.date
            )
            if best is None or value > best[0]:
                best = (value, transaction)
        return best[1] if best else None

    # ----------------------------------------------------------------- budgets
    def expense_history(self, months: int = 12) -> list[Transaction]:
        """Expenses from the recent ``months``, newest first."""
        cutoff = add_months(today_iso(), -max(1, int(months)))
        rows = self.conn.execute(
            _TXN_SELECT
            + " WHERE t.kind = 'expense' AND t.date >= ?"
            " ORDER BY t.date DESC, t.id DESC",
            (cutoff,),
        ).fetchall()
        return self._hydrate([self._transaction(row) for row in rows])

    def tag_breakdown(
        self, month: str | None = None, kind: str = "expense"
    ) -> list[CategorySpend]:
        """Spending grouped by tag (a transaction may appear under many tags)."""
        if kind not in ("expense", "income"):
            raise ValueError("类型必须是支出或收入")
        sql = (
            "SELECT tg.id, tg.name, tg.color, t.amount, t.currency, t.date"
            " FROM transactions t"
            " JOIN transaction_tags tt ON tt.transaction_id = t.id"
            " JOIN tags tg ON tg.id = tt.tag_id"
            " WHERE t.kind = ?"
        )
        params: list[object] = [kind]
        if month:
            start, end = month_bounds(month)
            sql += " AND t.date >= ? AND t.date < ?"
            params.extend([start, end])
        grouped: dict[int, list] = {}
        for row in self.conn.execute(sql, params):
            grouped.setdefault(int(row["id"]), []).append(row)
        result: list[CategorySpend] = []
        for rows in grouped.values():
            amount = sum(
                self._to_base(int(row["amount"]), row["currency"], row["date"])
                for row in rows
            )
            result.append(
                CategorySpend(
                    category_id=int(rows[0]["id"]),
                    name=rows[0]["name"],
                    color=rows[0]["color"],
                    amount=amount,
                )
            )
        result.sort(key=lambda item: (-item.amount, item.category_id))
        return result

    def daily_expense(self, month: str, kind: str = "expense") -> dict[str, int]:
        """Amount per day for a month, used by the spending calendar."""
        if kind not in ("expense", "income"):
            raise ValueError("类型必须是支出或收入")
        start, end = month_bounds(month)
        rows = self.conn.execute(
            "SELECT date, amount, currency FROM transactions"
            " WHERE kind = ? AND date >= ? AND date < ?",
            (kind, start, end),
        ).fetchall()
        totals: dict[str, int] = {}
        for row in rows:
            day = str(row["date"])
            totals[day] = totals.get(day, 0) + self._to_base(
                int(row["amount"]), row["currency"], day
            )
        return totals

    def _budget_spent(self, month: str, category_id: int) -> int:
        spent = {item.category_id: item.amount for item in self.category_breakdown(month)}
        return sum(spent.values()) if category_id == 0 else spent.get(category_id, 0)

    def _budget_carry(
        self, month: str, category_id: int, cache: dict[tuple[str, int], int]
    ) -> int:
        key = (month, category_id)
        if key in cache:
            return cache[key]
        previous = shift_month(month, -1)
        row = self.conn.execute(
            "SELECT amount, rollover FROM budgets WHERE month = ? AND category_id = ?",
            (previous, category_id),
        ).fetchone()
        if not row or not int(row["rollover"]):
            cache[key] = 0
            return 0
        available = int(row["amount"]) + self._budget_carry(
            previous, category_id, cache
        )
        carry = max(0, available - self._budget_spent(previous, category_id))
        cache[key] = carry
        return carry

    def budget_lines(self, month: str) -> list[BudgetLine]:
        parse_month(month)
        rows = self.conn.execute(
            "SELECT b.id, b.month, b.category_id, b.amount, b.rollover, c.name, c.color"
            " FROM budgets b LEFT JOIN categories c ON c.id = b.category_id"
            " WHERE b.month = ? ORDER BY (b.category_id = 0) DESC, b.amount DESC",
            (month,),
        ).fetchall()
        cache: dict[tuple[str, int], int] = {}
        lines: list[BudgetLine] = []
        for row in rows:
            category_id = int(row["category_id"])
            lines.append(
                BudgetLine(
                    id=int(row["id"]),
                    month=row["month"],
                    category_id=category_id,
                    name="本月总预算" if category_id == 0 else (row["name"] or "未分类"),
                    color="#5B8DEF" if category_id == 0 else (row["color"] or "#95A0B5"),
                    amount=int(row["amount"]),
                    spent=self._budget_spent(month, category_id),
                    rollover=self._budget_carry(month, category_id, cache),
                    rollover_enabled=bool(row["rollover"]),
                )
            )
        return lines

    def upsert_budget(
        self, month: str, category_id: int, amount: int, rollover: bool = False
    ) -> int:
        parse_month(month)
        category_id = int(category_id)
        if category_id:
            category = self.get_category(category_id)
            if category.kind != "expense":
                raise ValueError("预算只能用于支出分类")
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError("预算金额必须大于 0")
        if amount > MAX_AMOUNT_CENTS:
            raise ValueError("预算金额超出可记录范围")
        self.conn.execute(
            "INSERT INTO budgets (month, category_id, amount, rollover)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(month, category_id) DO UPDATE SET amount = excluded.amount,"
            " rollover = excluded.rollover",
            (month, category_id, amount, int(bool(rollover))),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM budgets WHERE month = ? AND category_id = ?",
            (month, category_id),
        ).fetchone()
        return int(row["id"])

    def delete_budget(self, budget_id: int) -> None:
        self.conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
        self.conn.commit()

    def total_budget(self, month: str) -> int:
        row = self.conn.execute(
            "SELECT amount FROM budgets WHERE month = ? AND category_id = 0", (month,)
        ).fetchone()
        return int(row["amount"]) if row else 0

    # --------------------------------------------------------- category rules
    def _category_rule(self, row: sqlite3.Row) -> CategoryRule:
        try:
            tags = tuple(json.loads(row["tags"] or "[]"))
        except (TypeError, ValueError):
            tags = ()
        return CategoryRule(
            id=int(row["id"]),
            pattern=str(row["pattern"]),
            kind=str(row["kind"]),
            category_id=int(row["category_id"]),
            category_name=str(row["category_name"] or ""),
            category_color=str(row["category_color"] or ""),
            tags=tags,
            hit_count=int(row["hit_count"] or 0),
            created_at=str(row["created_at"] or ""),
        )

    def category_rules(self) -> list[CategoryRule]:
        rows = self.conn.execute(
            "SELECT r.*, c.name AS category_name, c.color AS category_color"
            " FROM category_rules r JOIN categories c ON c.id = r.category_id"
            " ORDER BY r.kind, lower(r.pattern)"
        ).fetchall()
        return [self._category_rule(row) for row in rows]

    def get_category_rule(self, rule_id: int) -> CategoryRule:
        row = self.conn.execute(
            "SELECT r.*, c.name AS category_name, c.color AS category_color"
            " FROM category_rules r JOIN categories c ON c.id = r.category_id"
            " WHERE r.id = ?",
            (int(rule_id),),
        ).fetchone()
        if row is None:
            raise ValueError("分类规则不存在")
        return self._category_rule(row)

    def add_category_rule(
        self,
        pattern: str,
        kind: str,
        category_id: int,
        tags: Iterable[str] | None = None,
    ) -> int:
        pattern = str(pattern or "").strip()[:40]
        if not pattern:
            raise ValueError("匹配词不能为空")
        if kind not in ("expense", "income"):
            raise ValueError("规则类型无效")
        category = self.get_category(int(category_id))
        if category.kind != kind:
            raise ValueError("分类与规则类型不匹配")
        tag_names = self._normalize_tags(tags or [])
        try:
            cursor = self.conn.execute(
                "INSERT INTO category_rules"
                " (pattern, kind, category_id, tags, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    pattern,
                    kind,
                    int(category_id),
                    json.dumps(tag_names, ensure_ascii=False),
                    now_iso(),
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("同样的匹配规则已存在") from None
        return int(cursor.lastrowid)

    def update_category_rule(
        self,
        rule_id: int,
        *,
        pattern: str | None = None,
        category_id: int | None = None,
        tags: Iterable[str] | None = None,
    ) -> None:
        rule = self.get_category_rule(rule_id)
        pattern = (
            str(pattern).strip()[:40] if pattern is not None else rule.pattern
        )
        if not pattern:
            raise ValueError("匹配词不能为空")
        target = int(category_id) if category_id is not None else rule.category_id
        category = self.get_category(target)
        if category.kind != rule.kind:
            raise ValueError("分类与规则类型不匹配")
        tag_names = (
            self._normalize_tags(tags) if tags is not None else list(rule.tags)
        )
        try:
            self.conn.execute(
                "UPDATE category_rules SET pattern = ?, category_id = ?, tags = ?,"
                " updated_at = ? WHERE id = ?",
                (
                    pattern,
                    target,
                    json.dumps(tag_names, ensure_ascii=False),
                    now_iso(),
                    int(rule_id),
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("同样的匹配规则已存在") from None

    def delete_category_rule(self, rule_id: int) -> None:
        self.conn.execute(
            "DELETE FROM category_rules WHERE id = ?", (int(rule_id),)
        )
        self.conn.commit()

    def match_category_rule(self, payee: str, kind: str) -> CategoryRule | None:
        text = str(payee or "").strip().casefold()
        if not text:
            return None
        matches = [
            rule
            for rule in self.category_rules()
            if rule.kind == kind and rule.pattern.casefold() in text
        ]
        if not matches:
            return None
        return max(matches, key=lambda rule: (len(rule.pattern), -rule.id))

    def record_rule_hit(self, rule_id: int) -> None:
        self.conn.execute(
            "UPDATE category_rules SET hit_count = hit_count + 1, updated_at = ?"
            " WHERE id = ?",
            (now_iso(), int(rule_id)),
        )
        self.conn.commit()

    def learn_category_rules(self, min_count: int = 2) -> int:
        """Create rules for payees that always used one category and tag set."""
        rows = self.conn.execute(
            "SELECT lower(payee) AS key, MIN(payee) AS payee, kind, category_id,"
            "       COUNT(*) AS n"
            " FROM transactions"
            " WHERE kind IN ('expense','income') AND payee <> ''"
            "   AND category_id IS NOT NULL AND refund_of_id IS NULL"
            "   AND NOT EXISTS (SELECT 1 FROM transaction_splits s"
            "                   WHERE s.transaction_id = transactions.id)"
            " GROUP BY lower(payee), kind, category_id"
            " ORDER BY n DESC"
        ).fetchall()
        groups: dict[tuple[str, str], dict[str, object]] = {}
        for row in rows:
            key = (str(row["key"]), str(row["kind"]))
            bucket = groups.setdefault(
                key,
                {"payee": row["payee"], "cats": {}, "total": 0},
            )
            cats = bucket["cats"]  # type: ignore[assignment]
            cats[int(row["category_id"])] = int(row["n"])  # type: ignore[index]
            bucket["total"] = int(bucket["total"]) + int(row["n"])
        created = 0
        for (_, kind), bucket in groups.items():
            cats = bucket["cats"]  # type: ignore[assignment]
            if len(cats) != 1 or int(bucket["total"]) < max(2, int(min_count)):
                continue
            category_id = next(iter(cats))
            try:
                self.add_category_rule(
                    str(bucket["payee"]), kind, int(category_id)
                )
            except ValueError:
                continue
            created += 1
        return created

    def apply_rule_tags_to_history(self, rule_id: int | None = None) -> int:
        """Merge each rule's tags into matching historical transactions."""
        rules = [rule for rule in self.category_rules() if rule.tags]
        if rule_id is not None:
            rules = [rule for rule in rules if rule.id == int(rule_id)]
        if not rules:
            return 0
        rows = self.conn.execute(
            "SELECT id, payee, kind FROM transactions"
            " WHERE payee <> '' AND kind IN ('expense','income')"
        ).fetchall()
        changed = 0
        with self.db.transaction() as conn:
            for row in rows:
                text = str(row["payee"] or "").casefold()
                matches = [
                    rule
                    for rule in rules
                    if rule.kind == row["kind"] and rule.pattern.casefold() in text
                ]
                if not matches:
                    continue
                rule = max(matches, key=lambda item: (len(item.pattern), -item.id))
                existing = [
                    str(item["name"])
                    for item in conn.execute(
                        "SELECT t.name FROM tags t"
                        " JOIN transaction_tags tt ON tt.tag_id = t.id"
                        " WHERE tt.transaction_id = ?",
                        (int(row["id"]),),
                    )
                ]
                merged = self._normalize_tags([*existing, *rule.tags])
                if merged == self._normalize_tags(existing):
                    continue
                self._replace_tags(int(row["id"]), merged)
                changed += 1
        return changed

    # ------------------------------------------------------- transaction templates
    @staticmethod
    def _template(row: sqlite3.Row) -> TransactionTemplate:
        return TransactionTemplate(
            id=int(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            amount=int(row["amount"]),
            currency=str(row["currency"]),
            category_id=row["category_id"],
            category_name=str(row["category_name"] or ""),
            account_id=row["account_id"],
            account_name=str(row["account_name"] or ""),
            to_account_id=row["to_account_id"],
            to_account_name=str(row["to_account_name"] or ""),
            payee=str(row["payee"] or ""),
            note=str(row["note"] or ""),
            created_at=str(row["created_at"] or ""),
        )

    _TEMPLATE_SELECT = """
        SELECT t.id, t.name, t.kind, t.amount, t.currency,
               t.category_id, c.name AS category_name,
               t.account_id, a.name AS account_name,
               t.to_account_id, ta.name AS to_account_name,
               t.payee, t.note, t.created_at
        FROM transaction_templates t
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        LEFT JOIN accounts ta ON ta.id = t.to_account_id
    """

    def transaction_templates(self) -> list[TransactionTemplate]:
        rows = self.conn.execute(
            self._TEMPLATE_SELECT + " ORDER BY t.name COLLATE NOCASE, t.id"
        ).fetchall()
        return [self._template(row) for row in rows]

    def get_transaction_template(self, template_id: int) -> TransactionTemplate:
        row = self.conn.execute(
            self._TEMPLATE_SELECT + " WHERE t.id = ?", (template_id,)
        ).fetchone()
        if row is None:
            raise ValueError("模板不存在")
        return self._template(row)

    def _template_values(
        self,
        name: str,
        kind: str,
        amount: int,
        currency: str,
        category_id: int | None,
        account_id: int | None,
        to_account_id: int | None,
        payee: str,
        note: str,
    ) -> tuple:
        cleaned = self._clean_name(name, "模板名称")
        if kind not in ("expense", "income", "transfer"):
            raise ValueError("记录类型不正确")
        amount = int(amount or 0)
        if amount < 0 or amount > MAX_AMOUNT_CENTS:
            raise ValueError("金额超出范围")
        if currency not in CURRENCIES:
            raise ValueError("请选择有效的币种")
        if category_id is not None:
            category = self.get_category(int(category_id))
            if kind == "transfer":
                raise ValueError("转账模板不能选择分类")
            if category.kind != kind:
                raise ValueError("分类与记录类型不匹配")
        else:
            category_id = None
        if account_id is not None:
            account = self.get_account(int(account_id), include_archived=True)
            if account.is_system:
                raise ValueError("系统账户不能用于模板")
        if to_account_id is not None:
            target = self.get_account(int(to_account_id), include_archived=True)
            if target.is_system:
                raise ValueError("系统账户不能用于模板")
            if to_account_id == account_id:
                raise ValueError("转出账户和转入账户不能相同")
        if kind == "transfer" and to_account_id is None:
            raise ValueError("转账模板需要选择转入账户")
        return (
            cleaned,
            kind,
            amount,
            currency,
            category_id,
            account_id,
            to_account_id,
            str(payee or "").strip()[:60],
            str(note or "").strip()[:200],
        )

    def add_transaction_template(
        self,
        name: str,
        *,
        kind: str,
        amount: int = 0,
        currency: str = "CNY",
        category_id: int | None = None,
        account_id: int | None = None,
        to_account_id: int | None = None,
        payee: str = "",
        note: str = "",
    ) -> int:
        values = self._template_values(
            name,
            kind,
            amount,
            currency,
            category_id,
            account_id,
            to_account_id,
            payee,
            note,
        )
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO transaction_templates"
                " (name, kind, amount, currency, category_id, account_id,"
                "  to_account_id, payee, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*values, now_iso()),
            )
            return int(cursor.lastrowid)

    def update_transaction_template(self, template_id: int, **fields) -> None:
        current = self.get_transaction_template(template_id)
        values = self._template_values(
            fields.get("name", current.name),
            fields.get("kind", current.kind),
            fields.get("amount", current.amount),
            fields.get("currency", current.currency),
            fields.get("category_id", current.category_id),
            fields.get("account_id", current.account_id),
            fields.get("to_account_id", current.to_account_id),
            fields.get("payee", current.payee),
            fields.get("note", current.note),
        )
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE transaction_templates SET name = ?, kind = ?, amount = ?,"
                " currency = ?, category_id = ?, account_id = ?, to_account_id = ?,"
                " payee = ?, note = ?, updated_at = ? WHERE id = ?",
                (*values, now_iso(), template_id),
            )

    def delete_transaction_template(self, template_id: int) -> None:
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM transaction_templates WHERE id = ?", (template_id,)
            )
            if cursor.rowcount == 0:
                raise ValueError("模板不存在")

    # -------------------------------------------------------------- bulk / CSV
    def insert_normalized(self, rows: Iterable[dict]) -> int:
        """Insert already-validated rows in one transaction (used by CSV import)."""
        count = 0
        with self.db.transaction() as conn:
            for row in rows:
                source = row.get("currency") or "CNY"
                account = self.get_account(int(row["account_id"]), include_archived=True)
                posted = row.get("account_amount")
                if posted is None:
                    posted = self._converted(
                        int(row["amount"]), source, account.currency, row["date"]
                    )
                received = 0
                fee = 0
                if row["kind"] == "transfer":
                    target = self.get_account(
                        int(row["to_account_id"]), include_archived=True
                    )
                    received = row.get("to_amount")
                    if received is None:
                        received = self._converted(
                            int(row["amount"]), source, target.currency, row["date"]
                        )
                    fee = self.withdrawal_fee(int(row["account_id"]), int(posted))
                conn.execute(
                    "INSERT INTO transactions (date, kind, amount, currency,"
                    " account_amount, to_amount, fee, category_id, account_id,"
                    " to_account_id, payee, note, import_hash, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["date"],
                        row["kind"],
                        row["amount"],
                        source,
                        int(posted),
                        int(received),
                        fee,
                        row.get("category_id"),
                        row["account_id"],
                        row.get("to_account_id"),
                        row.get("payee", ""),
                        row.get("note", ""),
                        row.get("import_hash") or None,
                        now_iso(),
                    ),
                )
                count += 1
        return count

    # ------------------------------------------------------------------ resets
    def clear_all(self, *, seed_defaults: bool = True) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM transaction_templates")
            conn.execute("DELETE FROM term_deposits")
            conn.execute("DELETE FROM planned_transactions")
            conn.execute("DELETE FROM receivables")
            conn.execute("DELETE FROM debt_payments")
            conn.execute("DELETE FROM debts")
            conn.execute("DELETE FROM fixed_asset_valuations")
            conn.execute("DELETE FROM category_rules")
            conn.execute("DELETE FROM undo_log")
            conn.execute("DELETE FROM budgets")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM categories")
            conn.execute("DELETE FROM fixed_assets")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN"
                " ('transactions','budgets','accounts','categories',"
                "  'category_rules','undo_log','term_deposits',"
                "  'planned_transactions','receivables','debt_payments','debts',"
                "  'fixed_asset_valuations')"
            )
            if seed_defaults:
                Database._seed_defaults(conn)

    def summary_text(self) -> str:
        counts = {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("accounts", "categories", "transactions", "budgets")
        }
        return (
            f"{counts['accounts']} 个账户 · {counts['categories']} 个分类 · "
            f"{counts['transactions']} 笔记录 · {counts['budgets']} 条预算"
        )


def _valid_color(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        return False
    try:
        int(text[1:], 16)
    except ValueError:
        return False
    return True


def group_accounts(accounts: Sequence[Account]) -> tuple[list[Account], list[Account]]:
    """Split into (asset accounts, liability accounts), preserving input order."""
    assets = [account for account in accounts if ACCOUNT_TYPE_META[account.type]["group"] == "asset"]
    liabilities = [account for account in accounts if account.group == "liability"]
    return assets, liabilities
