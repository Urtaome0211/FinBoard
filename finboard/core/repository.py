"""Repository layer: every SQL statement lives here.

The repository speaks in integer cents and ISO date strings; it never imports
Qt.  That keeps the financial logic unit-testable without a display server.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence

from .database import Database
from .dates import (
    month_bounds,
    month_of,
    normalize_day,
    now_iso,
    parse_month,
    recent_months,
    today,
)
from .fees import calculate_withdrawal_fee
from .models import (
    ACCOUNT_TYPES,
    ACCOUNT_TYPE_META,
    Account,
    BudgetLine,
    Category,
    CategorySpend,
    FALLBACK_CATEGORY,
    KIND_LABELS,
    MonthStats,
    NetWorth,
    PayeeSpend,
    Transaction,
    TransactionFilter,
)
from .money import CURRENCIES, MAX_AMOUNT_CENTS
from .rates import RateError, RateStore

_TXN_SELECT = """
SELECT t.id, t.date, t.kind, t.amount, t.currency, t.account_amount, t.to_amount, t.fee,
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
            account_currency=row["account_currency"] or "CNY",
            to_account_currency=row["to_account_currency"] or "CNY",
        )

    # --------------------------------------------------------------- accounts
    def accounts(self, *, include_archived: bool = False) -> list[Account]:
        where = "" if include_archived else "WHERE a.archived = 0"
        rows = self.conn.execute(
            f"""
            SELECT a.id, a.name, a.type, a.opening_balance, a.note, a.archived,
                   a.currency,
                   a.opening_balance + COALESCE(SUM(CASE
                       WHEN t.kind = 'income'   AND t.account_id    = a.id THEN  t.account_amount
                       WHEN t.kind = 'expense'  AND t.account_id    = a.id THEN -t.account_amount
                       WHEN t.kind = 'transfer' AND t.account_id    = a.id
                            THEN -(t.account_amount + COALESCE(t.fee, 0))
                       WHEN t.kind = 'transfer' AND t.to_account_id = a.id THEN  t.to_amount
                       ELSE 0 END), 0) AS balance
            FROM accounts a
            LEFT JOIN transactions t
                   ON t.account_id = a.id OR t.to_account_id = a.id
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
        if new_currency != current.currency and self.account_usage(account_id):
            raise ValueError("该账户已有记录，不能修改币种；请新建一个账户")
        new_opening = (
            current.opening_balance if opening_balance is None else int(opening_balance)
        )
        if abs(new_opening) > MAX_AMOUNT_CENTS:
            raise ValueError("期初金额超出可记录范围")
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
        if kind == "transfer":
            target = self.get_account(to_account_id, include_archived=True)
            received = (
                self._converted(amount, currency, target.currency, date)
                if to_amount is None
                else int(to_amount)
            )
            if received <= 0:
                raise ValueError("到账金额必须大于 0")
            fee = self.withdrawal_fee(account_id, posted)
        cursor = self.conn.execute(
            "INSERT INTO transactions (date, kind, amount, currency, account_amount,"
            " to_amount, fee, category_id, account_id, to_account_id, payee, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date,
                kind,
                amount,
                currency,
                posted,
                received,
                fee,
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
        if kind == "transfer":
            target = self.get_account(to_account_id, include_archived=True)
            received = (
                self._converted(amount, currency, target.currency, date)
                if to_amount is None
                else int(to_amount)
            )
            if received <= 0:
                raise ValueError("到账金额必须大于 0")
            fee = self.withdrawal_fee(account_id, posted)
        self.conn.execute(
            "UPDATE transactions SET date = ?, kind = ?, amount = ?, currency = ?,"
            " account_amount = ?, to_amount = ?, fee = ?, category_id = ?, account_id = ?,"
            " to_account_id = ?, payee = ?, note = ?, updated_at = ? WHERE id = ?",
            (
                date,
                kind,
                amount,
                currency,
                posted,
                received,
                fee,
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
