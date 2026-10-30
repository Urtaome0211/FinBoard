"""Repository layer: every SQL statement lives here.

The repository speaks in integer cents and ISO date strings; it never imports
Qt.  That keeps the financial logic unit-testable without a display server.
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date as date_cls
from datetime import timedelta
from typing import Iterable, Sequence

from .database import Database
from .dates import (
    days_in_month,
    month_bounds,
    month_of,
    normalize_day,
    now_iso,
    parse_month,
    recent_months,
    today,
    today_iso,
)
from .fees import calculate_withdrawal_fee
from .models import (
    ACCOUNT_TYPES,
    ACCOUNT_TYPE_META,
    Account,
    AccountValuation,
    BudgetLine,
    Category,
    CategorySpend,
    FALLBACK_CATEGORY,
    KIND_LABELS,
    MonthStats,
    NetWorth,
    PayeeSpend,
    Reconciliation,
    RecurringTransaction,
    Transaction,
    TransactionBalance,
    TransactionFilter,
)
from .money import CURRENCIES, MAX_AMOUNT_CENTS
from .rates import RateError, RateStore

_TXN_SELECT = """
SELECT t.id, t.date, t.kind, t.amount, t.currency, t.account_amount, t.to_amount, t.fee,
       t.fee_waived, t.fee_included,
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
            account_currency=row["account_currency"] or "CNY",
            to_account_currency=row["to_account_currency"] or "CNY",
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
                   a.currency, a.adjustment,
                   vc.valuation_count AS valuation_count,
                   lv.value AS last_valuation,
                   lv.date AS last_valuation_date,
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
                   END AS balance
            FROM accounts a
            LEFT JOIN transactions t
                   ON t.account_id = a.id OR t.to_account_id = a.id
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

    def withdrawal_fee(self, account_id: int, account_amount: int) -> int:
        """Fee charged when this account sends money out, in account cents."""
        account = self.get_account(account_id, include_archived=True)
        return calculate_withdrawal_fee(
            account.name, int(account_amount), account.currency
        )

    def _available_before(
        self, account_id: int, exclude_transaction_id: int | None = None
    ) -> int:
        """Balance available to a new transfer, excluding an edited row."""
        balance = self.account_balance(account_id)
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
        new_name = current.name if name is None else self._clean_name(name, "账户名称", 30)
        new_type = current.type if type_ is None else type_
        if new_type not in ACCOUNT_TYPES:
            raise ValueError("账户类型无效")
        new_currency = current.currency if currency is None else currency
        if new_currency not in CURRENCIES:
            raise ValueError("不支持的币种")
        if new_currency != current.currency and (
            self.account_usage(account_id) or current.valuation_count
        ):
            raise ValueError("该账户已有记录，不能修改币种；请新建一个账户")
        if new_type != "investment" and current.valuation_count:
            raise ValueError("该账户已有市值记录，不能改为非投资账户")
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
        self.conn.execute(
            "UPDATE accounts SET archived = ? WHERE id = ?", (int(archived), account_id)
        )
        self.conn.commit()

    def delete_account(self, account_id: int) -> None:
        used = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id = ? OR to_account_id = ?",
            (account_id, account_id),
        ).fetchone()[0]
        if used:
            raise ValueError("该账户已有记录，无法删除；可以改为归档")
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
    def _where_clause(self, filters: TransactionFilter) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if filters.month:
            start, end = month_bounds(filters.month)
            clauses.append("t.date >= ? AND t.date < ?")
            params.extend([start, end])
        if filters.kind:
            clauses.append("t.kind = ?")
            params.append(filters.kind)
        if filters.category_id:
            clauses.append("t.category_id = ?")
            params.append(filters.category_id)
        if filters.account_id:
            clauses.append("(t.account_id = ? OR t.to_account_id = ?)")
            params.extend([filters.account_id, filters.account_id])
        search = (filters.search or "").strip()
        if search:
            like = f"%{search}%"
            clauses.append(
                "(t.payee LIKE ? OR t.note LIKE ? OR COALESCE(c.name,'') LIKE ?"
                " OR a.name LIKE ? OR COALESCE(ta.name,'') LIKE ?)"
            )
            params.extend([like, like, like, like, like])
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
        return [self._transaction(row) for row in rows]

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
        return [self._transaction(row) for row in rows]

    def get_transaction(self, transaction_id: int) -> Transaction:
        row = self.conn.execute(
            _TXN_SELECT + " WHERE t.id = ?", (transaction_id,)
        ).fetchone()
        if not row:
            raise ValueError("记录不存在")
        return self._transaction(row)

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
            " to_amount, fee, fee_waived, fee_included, category_id, account_id,"
            " to_account_id, payee, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                category_id,
                account_id,
                to_account_id,
                str(payee or "").strip()[:60],
                str(note or "").strip()[:200],
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

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
    ) -> None:
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
        self.conn.execute(
            "UPDATE transactions SET date = ?, kind = ?, amount = ?, currency = ?,"
            " account_amount = ?, to_amount = ?, fee = ?, fee_waived = ?,"
            " fee_included = ?, category_id = ?, account_id = ?,"
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
                category_id,
                account_id,
                to_account_id,
                str(payee or "").strip()[:60],
                str(note or "").strip()[:200],
                now_iso(),
                transaction_id,
            ),
        )
        self.conn.commit()

    def delete_transaction(self, transaction_id: int) -> None:
        self.conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        self.conn.commit()

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
            "SELECT t.kind, t.amount, t.currency, t.date, t.fee,"
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
            totals[row["kind"]] += self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
        return MonthStats(
            month=month, income=totals["income"], expense=totals["expense"]
        )

    def net_worth(self) -> NetWorth:
        accounts = self.accounts(include_archived=False)
        assets = 0
        liabilities = 0
        for account in accounts:
            value = self._to_base(account.balance, account.currency)
            if account.group == "liability":
                # Liability accounts hold their face value; accepting a positive
                # opening balance must not silently turn debt into an asset.
                liabilities += abs(value)
            else:
                assets += value
        return NetWorth(
            assets=assets,
            liabilities=liabilities,
            asset_accounts=sum(1 for account in accounts if account.group == "asset"),
            liability_accounts=sum(1 for account in accounts if account.group == "liability"),
        )

    def trend(self, months: int = 12, end_month: str | None = None) -> list[MonthStats]:
        months = max(1, min(int(months), 60))
        end_month = end_month or month_of(today())
        labels = recent_months(months, end_month)
        start, _ = month_bounds(labels[0])
        _, end = month_bounds(labels[-1])
        rows = self.conn.execute(
            "SELECT substr(t.date, 1, 7) AS month, t.kind, t.amount, t.currency,"
            "       t.date, t.fee, a.currency AS account_currency"
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
            bucket[row["kind"]] += self._to_base(
                int(row["amount"]), row["currency"], row["date"]
            )
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
        rows = self.conn.execute(
            "SELECT c.id, c.name, c.color, t.amount, t.currency, t.date"
            " FROM transactions t JOIN categories c ON c.id = t.category_id"
            " WHERE t.kind = ?" + date_clause,
            params,
        ).fetchall()
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
        result = [
            CategorySpend(
                category_id=category_id,
                name=str(item["name"]),
                color=str(item["color"]),
                amount=int(item["amount"]),
            )
            for category_id, item in grouped.items()
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
        ordered = sorted(totals.items(), key=lambda item: (-item[1][0], item[0]))
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
        best: tuple[int, Transaction] | None = None
        for row in rows:
            transaction = self._transaction(row)
            value = self._to_base(
                transaction.amount, transaction.currency, transaction.date
            )
            if best is None or value > best[0]:
                best = (value, transaction)
        return best[1] if best else None

    # ----------------------------------------------------------------- budgets
    def budget_lines(self, month: str) -> list[BudgetLine]:
        parse_month(month)
        rows = self.conn.execute(
            "SELECT b.id, b.month, b.category_id, b.amount, c.name, c.color"
            " FROM budgets b LEFT JOIN categories c ON c.id = b.category_id"
            " WHERE b.month = ? ORDER BY (b.category_id = 0) DESC, b.amount DESC",
            (month,),
        ).fetchall()
        spent = {item.category_id: item.amount for item in self.category_breakdown(month)}
        total_spent = sum(spent.values())
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
                    spent=total_spent if category_id == 0 else spent.get(category_id, 0),
                )
            )
        return lines

    def upsert_budget(self, month: str, category_id: int, amount: int) -> int:
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
            "INSERT INTO budgets (month, category_id, amount) VALUES (?, ?, ?)"
            " ON CONFLICT(month, category_id) DO UPDATE SET amount = excluded.amount",
            (month, category_id, amount),
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
                    " to_account_id, payee, note, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        now_iso(),
                    ),
                )
                count += 1
        return count

    # ------------------------------------------------------------------ resets
    def clear_all(self, *, seed_defaults: bool = True) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM budgets")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM categories")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN"
                " ('transactions','budgets','accounts','categories')"
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
