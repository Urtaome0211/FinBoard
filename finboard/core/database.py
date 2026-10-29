"""SQLite database bootstrap and schema migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .dates import now_iso
from .models import DEFAULT_CATEGORIES

SCHEMA_VERSION = 3

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    type            TEXT    NOT NULL CHECK (type IN ('cash','debit','credit','loan','investment')),
    opening_balance INTEGER NOT NULL DEFAULT 0,
    note            TEXT    NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1)),
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT    NOT NULL,
    kind    TEXT    NOT NULL CHECK (kind IN ('expense','income')),
    color   TEXT    NOT NULL DEFAULT '#95A0B5',
    created_at TEXT NOT NULL,
    UNIQUE (name, kind)
);

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('expense','income','transfer')),
    amount        INTEGER NOT NULL CHECK (amount > 0),
    category_id   INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    to_account_id INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    payee         TEXT    NOT NULL DEFAULT '',
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT,
    CHECK (
        (kind = 'transfer'
            AND category_id IS NULL
            AND to_account_id IS NOT NULL
            AND to_account_id <> account_id)
        OR
        (kind IN ('expense','income')
            AND category_id IS NOT NULL
            AND to_account_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS budgets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    month       TEXT    NOT NULL,
    category_id INTEGER NOT NULL DEFAULT 0,
    amount      INTEGER NOT NULL CHECK (amount > 0),
    UNIQUE (month, category_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_budgets_month ON budgets(month);
"""

SCHEMA_V2 = """
ALTER TABLE accounts ADD COLUMN currency TEXT NOT NULL DEFAULT 'CNY';

ALTER TABLE transactions ADD COLUMN currency TEXT NOT NULL DEFAULT 'CNY';
ALTER TABLE transactions ADD COLUMN account_amount INTEGER NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN to_amount INTEGER NOT NULL DEFAULT 0;

UPDATE transactions SET account_amount = amount WHERE account_amount = 0;
UPDATE transactions SET to_amount = amount
 WHERE kind = 'transfer' AND to_amount = 0;

CREATE TABLE IF NOT EXISTS exchange_rates (
    date       TEXT NOT NULL,
    currency   TEXT NOT NULL,
    rate       REAL NOT NULL CHECK (rate > 0),
    source     TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (date, currency)
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rates_date ON exchange_rates(date);
"""

SCHEMA_V3 = """
ALTER TABLE transactions ADD COLUMN fee INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0);
"""


class Database:
    """Owns the SQLite connection and the schema lifecycle."""

    def __init__(self, path: str | Path | None = None, *, seed: bool = True) -> None:
        if path is None:
            raise ValueError("A database path is required")
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self.seed_defaults = seed
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ setup
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        assert self._conn is not None
        return self._conn

    def _connect(self) -> None:
        target = str(self.path)
        if target != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if target != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        self._conn = conn
        self._migrate()

    def _migrate(self) -> None:
        conn = self.conn
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version < 1:
            conn.executescript(SCHEMA_V1)
            if self.seed_defaults:
                self._seed_defaults(conn)
            version = 1
        if version < 2:
            conn.executescript(SCHEMA_V2)
            version = 2
        if version < 3:
            conn.executescript(SCHEMA_V3)
            version = 3
        if version < SCHEMA_VERSION:
            raise RuntimeError(f"Unsupported database schema version: {version}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

    @staticmethod
    def _seed_defaults(conn: sqlite3.Connection) -> None:
        stamp = now_iso()
        category_count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if not category_count:
            conn.executemany(
                "INSERT INTO categories (name, kind, color, created_at) VALUES (?, ?, ?, ?)",
                [(name, kind, color, stamp) for name, kind, color in DEFAULT_CATEGORIES],
            )
        account_count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        if not account_count:
            conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, note, created_at)"
                " VALUES (?, 'cash', 0, '', ?)",
                ("现金", stamp),
            )

    def seed_defaults(self) -> None:
        """Insert default categories/accounts when both tables are empty."""
        with self.transaction() as conn:
            self._seed_defaults(conn)

    # ---------------------------------------------------------------- queries
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Explicit transaction; nested calls reuse the open transaction."""
        conn = self.conn
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
