"""SQLite database bootstrap and schema migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .dates import now_iso
from .models import DEFAULT_CATEGORIES

SCHEMA_VERSION = 17

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

SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS account_valuations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date       TEXT    NOT NULL,
    value      INTEGER NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    UNIQUE (account_id, date)
);

CREATE INDEX IF NOT EXISTS idx_valuations_account_date
    ON account_valuations(account_id, date);
"""

SCHEMA_V5 = """
ALTER TABLE transactions ADD COLUMN fee_waived INTEGER NOT NULL DEFAULT 0
    CHECK (fee_waived IN (0,1));
ALTER TABLE transactions ADD COLUMN fee_included INTEGER NOT NULL DEFAULT 0
    CHECK (fee_included IN (0,1));
"""

SCHEMA_V6 = """
ALTER TABLE accounts ADD COLUMN adjustment INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS recurring_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN ('expense','income','transfer')),
    amount         INTEGER NOT NULL CHECK (amount > 0),
    currency       TEXT    NOT NULL DEFAULT 'CNY',
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    category_id    INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    to_account_id  INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    payee          TEXT    NOT NULL DEFAULT '',
    note           TEXT    NOT NULL DEFAULT '',
    fee_waived     INTEGER NOT NULL DEFAULT 0 CHECK (fee_waived IN (0,1)),
    frequency      TEXT    NOT NULL CHECK (frequency IN ('daily','weekly','monthly','yearly')),
    interval_count INTEGER NOT NULL DEFAULT 1 CHECK (interval_count BETWEEN 1 AND 365),
    start_date     TEXT    NOT NULL,
    end_date       TEXT,
    next_date      TEXT    NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_at     TEXT    NOT NULL,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_recurring_next
    ON recurring_transactions(active, next_date);

CREATE TABLE IF NOT EXISTS account_reconciliations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id        INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date              TEXT    NOT NULL,
    statement_balance INTEGER NOT NULL,
    ledger_balance    INTEGER NOT NULL,
    difference        INTEGER NOT NULL,
    note              TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reconciliations_account
    ON account_reconciliations(account_id, date);
"""

SCHEMA_V8 = """
ALTER TABLE accounts ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;
UPDATE accounts SET sort_order = id WHERE sort_order = 0;
CREATE INDEX IF NOT EXISTS idx_accounts_sort ON accounts(sort_order);
"""

SCHEMA_V9 = """
DROP INDEX IF EXISTS idx_accounts_sort;
ALTER TABLE accounts DROP COLUMN sort_order;
"""

SCHEMA_V10 = """
ALTER TABLE transactions ADD COLUMN import_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_import_hash
    ON transactions(import_hash) WHERE import_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    color      TEXT    NOT NULL DEFAULT '#5B8DEF',
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag_id         INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (transaction_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_transaction_tags_tag
    ON transaction_tags(tag_id, transaction_id);

CREATE TABLE IF NOT EXISTS transaction_splits (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    category_id    INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    amount         INTEGER NOT NULL CHECK (amount > 0),
    note           TEXT    NOT NULL DEFAULT '',
    position       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_splits_transaction
    ON transaction_splits(transaction_id, position);

CREATE TABLE IF NOT EXISTS attachments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    filename       TEXT    NOT NULL,
    stored_name    TEXT    NOT NULL,
    mime_type      TEXT    NOT NULL DEFAULT '',
    size           INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attachments_transaction
    ON attachments(transaction_id);

CREATE TABLE IF NOT EXISTS csv_import_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    mapping             TEXT    NOT NULL DEFAULT '{}',
    default_kind        TEXT    NOT NULL DEFAULT 'expense',
    default_account_id  INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    dedup               INTEGER NOT NULL DEFAULT 1 CHECK (dedup IN (0,1)),
    created_at          TEXT    NOT NULL,
    updated_at          TEXT
);
"""

SCHEMA_V7 = """
ALTER TABLE budgets ADD COLUMN rollover INTEGER NOT NULL DEFAULT 0
    CHECK (rollover IN (0,1));

ALTER TABLE transactions ADD COLUMN recurring_id INTEGER
    REFERENCES recurring_transactions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS holdings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol        TEXT    NOT NULL DEFAULT '',
    name          TEXT    NOT NULL,
    quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
    cost_price    INTEGER NOT NULL CHECK (cost_price >= 0),
    price         INTEGER NOT NULL CHECK (price >= 0),
    note          TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings(account_id);

CREATE TABLE IF NOT EXISTS savings_goals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    target_amount INTEGER NOT NULL CHECK (target_amount > 0),
    saved_amount  INTEGER NOT NULL DEFAULT 0 CHECK (saved_amount >= 0),
    target_date   TEXT,
    note          TEXT    NOT NULL DEFAULT '',
    archived      INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1)),
    created_at    TEXT    NOT NULL,
    updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_savings_goals_date ON savings_goals(target_date);
"""


SCHEMA_V11 = """
ALTER TABLE holdings ADD COLUMN realized_profit INTEGER NOT NULL DEFAULT 0;
ALTER TABLE holdings ADD COLUMN dividends INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS undo_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT    NOT NULL,
    payload    TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_undo_log_created ON undo_log(created_at, id);
"""


SCHEMA_V12 = """
CREATE TABLE IF NOT EXISTS fixed_assets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    type           TEXT    NOT NULL CHECK (type IN ('property','vehicle','other')),
    purchase_price INTEGER NOT NULL DEFAULT 0 CHECK (purchase_price >= 0),
    current_value  INTEGER NOT NULL DEFAULT 0 CHECK (current_value >= 0),
    valuation_date TEXT    NOT NULL,
    currency       TEXT    NOT NULL DEFAULT 'CNY',
    note           TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_fixed_assets_value ON fixed_assets(current_value);
"""


SCHEMA_V13 = """
ALTER TABLE transactions ADD COLUMN refund_of_id INTEGER
    REFERENCES transactions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_transactions_refund
    ON transactions(refund_of_id);

CREATE TABLE IF NOT EXISTS category_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL,
    kind        TEXT    NOT NULL CHECK (kind IN ('expense','income')),
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    tags        TEXT    NOT NULL DEFAULT '[]',
    hit_count   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_unique
    ON category_rules(lower(pattern), kind);

CREATE INDEX IF NOT EXISTS idx_category_rules_kind
    ON category_rules(kind);
"""


SCHEMA_V14 = """
ALTER TABLE accounts ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS term_deposits (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    name                   TEXT    NOT NULL,
    principal              INTEGER NOT NULL CHECK (principal > 0),
    currency               TEXT    NOT NULL DEFAULT 'CNY',
    annual_rate_bp         INTEGER NOT NULL CHECK (annual_rate_bp >= 0),
    term_months            INTEGER NOT NULL CHECK (term_months > 0),
    start_date             TEXT    NOT NULL,
    maturity_date          TEXT    NOT NULL,
    early_rate_bp          INTEGER NOT NULL DEFAULT 20 CHECK (early_rate_bp >= 0),
    source_account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    deposit_account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    destination_account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    status                 TEXT    NOT NULL DEFAULT 'active'
                                   CHECK (status IN ('active','closed')),
    close_reason           TEXT    NOT NULL DEFAULT ''
                                   CHECK (close_reason IN ('','matured','early')),
    interest_paid          INTEGER NOT NULL DEFAULT 0 CHECK (interest_paid >= 0),
    closed_at              TEXT,
    note                   TEXT    NOT NULL DEFAULT '',
    created_at             TEXT    NOT NULL,
    updated_at             TEXT
);

CREATE INDEX IF NOT EXISTS idx_term_deposits_status
    ON term_deposits(status, maturity_date);
"""


SCHEMA_V15 = """
ALTER TABLE holdings ADD COLUMN asset_class TEXT NOT NULL DEFAULT '';
ALTER TABLE holdings ADD COLUMN region TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS fixed_asset_valuations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   INTEGER NOT NULL REFERENCES fixed_assets(id) ON DELETE CASCADE,
    value      INTEGER NOT NULL CHECK (value >= 0),
    valued_on  TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    UNIQUE (asset_id, valued_on)
);

CREATE INDEX IF NOT EXISTS idx_fixed_asset_valuations_date
    ON fixed_asset_valuations(valued_on, asset_id);

INSERT OR IGNORE INTO fixed_asset_valuations
    (asset_id, value, valued_on, note, created_at)
SELECT id, current_value, valuation_date, '', created_at FROM fixed_assets;

CREATE TABLE IF NOT EXISTS debts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
    kind           TEXT    NOT NULL CHECK (kind IN ('loan','credit')),
    principal      INTEGER NOT NULL DEFAULT 0 CHECK (principal >= 0),
    annual_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK (annual_rate_bp >= 0),
    term_months    INTEGER NOT NULL DEFAULT 0 CHECK (term_months >= 0),
    start_date     TEXT,
    payment_method TEXT    NOT NULL DEFAULT 'equal_payment'
                           CHECK (payment_method IN ('equal_payment','equal_principal')),
    billing_day    INTEGER CHECK (billing_day BETWEEN 1 AND 28),
    due_day        INTEGER CHECK (due_day BETWEEN 1 AND 28),
    credit_limit   INTEGER NOT NULL DEFAULT 0 CHECK (credit_limit >= 0),
    min_payment_bp INTEGER NOT NULL DEFAULT 1000
                           CHECK (min_payment_bp BETWEEN 0 AND 10000),
    note           TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS planned_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT    NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN ('expense','income','transfer')),
    amount         INTEGER NOT NULL CHECK (amount > 0),
    currency       TEXT    NOT NULL DEFAULT 'CNY',
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    to_account_id  INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    category_id    INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
    payee          TEXT    NOT NULL DEFAULT '',
    note           TEXT    NOT NULL DEFAULT '',
    status         TEXT    NOT NULL DEFAULT 'planned'
                           CHECK (status IN ('planned','done','cancelled')),
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_planned_transactions_date
    ON planned_transactions(status, date);

CREATE TABLE IF NOT EXISTS receivables (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    direction    TEXT    NOT NULL CHECK (direction IN ('receivable','payable')),
    counterparty TEXT    NOT NULL,
    amount       INTEGER NOT NULL CHECK (amount > 0),
    currency     TEXT    NOT NULL DEFAULT 'CNY',
    date         TEXT    NOT NULL,
    due_date     TEXT,
    account_id   INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    note         TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open','settled')),
    settled_at   TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_receivables_status
    ON receivables(status, due_date);
"""


SCHEMA_V16 = """
CREATE TABLE IF NOT EXISTS investment_trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol         TEXT    NOT NULL DEFAULT '',
    name           TEXT    NOT NULL,
    kind           TEXT    NOT NULL CHECK (kind IN ('buy','sell','dividend')),
    trade_date     TEXT    NOT NULL,
    quantity_units INTEGER NOT NULL DEFAULT 0 CHECK (quantity_units >= 0),
    price          INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0),
    fee            INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    amount         INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    currency       TEXT    NOT NULL DEFAULT 'CNY',
    note           TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL,
    CHECK ((kind IN ('buy','sell') AND quantity_units > 0)
           OR (kind = 'dividend' AND amount > 0))
);

CREATE INDEX IF NOT EXISTS idx_investment_trades_account
    ON investment_trades(account_id, trade_date, id);
CREATE INDEX IF NOT EXISTS idx_investment_trades_symbol
    ON investment_trades(account_id, symbol, name);

CREATE TABLE IF NOT EXISTS investment_lots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL REFERENCES investment_trades(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol          TEXT    NOT NULL DEFAULT '',
    name            TEXT    NOT NULL,
    acquired_date   TEXT    NOT NULL,
    quantity_units  INTEGER NOT NULL CHECK (quantity_units > 0),
    remaining_units INTEGER NOT NULL CHECK (remaining_units >= 0),
    unit_cost       INTEGER NOT NULL CHECK (unit_cost >= 0),
    currency        TEXT    NOT NULL DEFAULT 'CNY',
    created_at      TEXT    NOT NULL,
    CHECK (remaining_units <= quantity_units)
);

CREATE INDEX IF NOT EXISTS idx_investment_lots_open
    ON investment_lots(account_id, symbol, name, remaining_units);

CREATE TABLE IF NOT EXISTS investment_disposals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sell_trade_id  INTEGER NOT NULL REFERENCES investment_trades(id) ON DELETE CASCADE,
    lot_id         INTEGER NOT NULL REFERENCES investment_lots(id) ON DELETE CASCADE,
    quantity_units INTEGER NOT NULL CHECK (quantity_units > 0),
    cost           INTEGER NOT NULL CHECK (cost >= 0),
    proceeds       INTEGER NOT NULL,
    realized       INTEGER NOT NULL,
    created_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_investment_disposals_trade
    ON investment_disposals(sell_trade_id);

INSERT INTO investment_trades
    (account_id, symbol, name, kind, trade_date, quantity_units, price, fee,
     amount, currency, note, created_at)
SELECT h.account_id, h.symbol, h.name, 'buy',
       substr(h.created_at, 1, 10), h.quantity_units, h.cost_price, 0, 0,
       a.currency, '从持仓快照迁移', h.created_at
FROM holdings h JOIN accounts a ON a.id = h.account_id
WHERE h.quantity_units > 0;

INSERT INTO investment_lots
    (trade_id, account_id, symbol, name, acquired_date, quantity_units,
     remaining_units, unit_cost, currency, created_at)
SELECT t.id, t.account_id, t.symbol, t.name, t.trade_date,
       t.quantity_units, t.quantity_units, t.price, t.currency, t.created_at
FROM investment_trades t
WHERE t.note = '从持仓快照迁移';
"""


SCHEMA_V17 = """
CREATE TABLE IF NOT EXISTS debt_payments (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id              INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    paid_on                 TEXT    NOT NULL,
    amount                  INTEGER NOT NULL CHECK (amount > 0),
    principal               INTEGER NOT NULL DEFAULT 0 CHECK (principal >= 0),
    interest                INTEGER NOT NULL DEFAULT 0 CHECK (interest >= 0),
    transfer_id             INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    interest_transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    note                    TEXT    NOT NULL DEFAULT '',
    created_at              TEXT    NOT NULL,
    CHECK (principal + interest = amount)
);

CREATE INDEX IF NOT EXISTS idx_debt_payments_account
    ON debt_payments(account_id, paid_on, id);
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
        if version < 4:
            conn.executescript(SCHEMA_V4)
            version = 4
        if version < 5:
            conn.executescript(SCHEMA_V5)
            version = 5
        if version < 6:
            conn.executescript(SCHEMA_V6)
            version = 6
        if version < 7:
            conn.executescript(SCHEMA_V7)
            version = 7
        if version < 8:
            conn.executescript(SCHEMA_V8)
            version = 8
        if version < 9:
            conn.executescript(SCHEMA_V9)
            version = 9
        if version < 10:
            conn.executescript(SCHEMA_V10)
            version = 10
        if version < 11:
            conn.executescript(SCHEMA_V11)
            version = 11
        if version < 12:
            conn.executescript(SCHEMA_V12)
            version = 12
        if version < 13:
            conn.executescript(SCHEMA_V13)
            version = 13
        if version < 14:
            conn.executescript(SCHEMA_V14)
            version = 14
        if version < 15:
            conn.executescript(SCHEMA_V15)
            version = 15
        if version < 16:
            conn.executescript(SCHEMA_V16)
            version = 16
        if version < 17:
            conn.executescript(SCHEMA_V17)
            version = 17
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
