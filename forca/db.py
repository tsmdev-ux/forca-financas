"""SQLite. Dinheiro é sempre inteiro em centavos; datas são texto ISO."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from . import config, parser

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    closing_day INTEGER NOT NULL,
    due_day INTEGER NOT NULL,
    limit_cents INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);

-- O que se repete todo mês: renda (income) e contas fixas (expense).
CREATE TABLE IF NOT EXISTS recurring (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    day INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'contas',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    balance_cents INTEGER NOT NULL,
    monthly_rate REAL NOT NULL DEFAULT 0,
    min_payment_cents INTEGER NOT NULL DEFAULT 0,
    due_day INTEGER NOT NULL DEFAULT 10,
    overdue INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('expense', 'income', 'transfer')),
    amount_cents INTEGER NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'outros',
    date TEXT NOT NULL,
    budget_month TEXT NOT NULL,      -- mês cujo orçamento paga este lançamento
    committed INTEGER NOT NULL DEFAULT 0,  -- já era compromisso (parcela antiga, fatura herdada)
    card_id INTEGER REFERENCES cards(id),
    invoice_month TEXT,              -- mês em que a fatura vence
    group_id TEXT,                   -- parcelas da mesma compra
    installment_no INTEGER,
    installment_total INTEGER,
    recurring_id INTEGER REFERENCES recurring(id),
    debt_id INTEGER REFERENCES debts(id),
    source TEXT NOT NULL DEFAULT 'app',
    batch_id TEXT,                   -- importação de origem, para desfazer em bloco
    external_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS tx_budget ON transactions (budget_month);
CREATE INDEX IF NOT EXISTS tx_date ON transactions (date);
CREATE UNIQUE INDEX IF NOT EXISTS tx_hash ON transactions (external_hash) WHERE external_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS invoice_payments (
    card_id INTEGER NOT NULL REFERENCES cards(id),
    invoice_month TEXT NOT NULL,
    paid_at TEXT NOT NULL,
    PRIMARY KEY (card_id, invoice_month)
);

CREATE TABLE IF NOT EXISTS categories (
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '•',
    builtin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

-- Metas: guardar não é gastar, e o plano mensal reserva o dinheiro no orçamento.
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    due_month TEXT,
    monthly_cents INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS goal_deposits (
    id INTEGER PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES goals(id),
    amount_cents INTEGER NOT NULL,
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_budgets (category TEXT PRIMARY KEY, limit_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS merchant_categories (merchant TEXT PRIMARY KEY, category TEXT NOT NULL);

-- Freio de impulso: a compra espera 24h antes de virar gasto.
CREATE TABLE IF NOT EXISTS pauses (
    id INTEGER PRIMARY KEY,
    item TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    installments INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'bought', 'skipped'))
);

-- Dias confirmados sem gasto ("hoje foi zero").
CREATE TABLE IF NOT EXISTS zero_days (date TEXT PRIMARY KEY);

-- Cada aviso sai uma vez só, mesmo que o processo reinicie.
CREATE TABLE IF NOT EXISTS nudge_log (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        c.executemany(
            "INSERT OR IGNORE INTO categories (key, label, icon, builtin) VALUES (?, ?, ?, 1)", parser.CATEGORY_SEED
        )
        c.executemany(
            "UPDATE categories SET icon = ? WHERE key = ? AND builtin = 1",
            [(icon, key) for key, _, icon in parser.CATEGORY_SEED],
        )


def category_label(key: str) -> str:
    conn = connect()
    try:
        row = conn.execute("SELECT label FROM categories WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row["label"] if row else key.capitalize()


def get_setting(c: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(c: sqlite3.Connection, key: str, value: str) -> None:
    c.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
