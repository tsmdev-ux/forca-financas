"""Tudo que escreve lançamentos passa por aqui, seja do Telegram, do app ou do agente."""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, timedelta

from . import config, db
from .finance import add_months, day_in_month, invoice_month_for, month_of
from .parser import guess_category, normalize


def learned_categories(c: sqlite3.Connection) -> dict:
    return {r["merchant"]: r["category"] for r in c.execute("SELECT * FROM merchant_categories")}


def ensure_started(c: sqlite3.Connection, day: date) -> None:
    """Marca quando o uso começou. Importar extrato antigo não muda isso: contas
    de antes do começo não viram atrasadas, nem o passado vira déficit."""
    if not db.get_setting(c, "started_month"):
        db.set_setting(c, "started_month", month_of(day))
        db.set_setting(c, "started_date", day.isoformat())


def find_card(c: sqlite3.Connection, hint: str | None) -> sqlite3.Row | None:
    """`*` significa "no cartão" sem dizer qual: só resolve quando existe um único."""
    if not hint:
        return None
    cards = c.execute("SELECT * FROM cards WHERE active = 1").fetchall()
    if hint == "*":
        return cards[0] if len(cards) == 1 else None
    norm = normalize(hint)
    for card in cards:
        if normalize(card["name"]) == norm:
            return card
    return None


def match_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", normalize(name)) if len(w) > 2}


def match_recurring(c: sqlite3.Connection, kind: str, description: str, amount: int, month: str) -> sqlite3.Row | None:
    """ "aluguel 1200" é a conta fixa Aluguel: sem esse vínculo, ela contaria duas vezes."""
    words = match_words(description)
    if not words:
        return None
    for r in c.execute("SELECT * FROM recurring WHERE active = 1 AND kind = ?", (kind,)).fetchall():
        if not (match_words(r["name"]) & words):
            continue
        if c.execute(
            "SELECT 1 FROM transactions WHERE recurring_id = ? AND budget_month = ?", (r["id"], month)
        ).fetchone():
            continue
        if r["amount_cents"] * 0.6 <= amount <= r["amount_cents"] * 1.5:
            return r
    return None


def match_debt(c: sqlite3.Connection, description: str) -> sqlite3.Row | None:
    words = match_words(description) - {"parcela", "divida", "emprestimo", "acordo"}
    if not words:
        return None
    for d in c.execute("SELECT * FROM debts WHERE active = 1").fetchall():
        if match_words(d["name"]) & words:
            return d
    return None


def add_expense(
    c: sqlite3.Connection,
    amount_cents: int,
    description: str,
    day: date,
    *,
    category: str | None = None,
    installments: int = 1,
    card: sqlite3.Row | None = None,
    source: str = "app",
    batch_id: str | None = None,
    external_hash: str | None = None,
    first_installment: int = 1,
    link: bool = True,
) -> dict:
    """Registra um gasto. Se bater com conta fixa ou dívida, liga em vez de duplicar.
    Retorna o que foi feito, para a resposta explicar."""
    ensure_started(c, config.today())
    if category is None:
        category = guess_category(description, learned_categories(c))
    month = month_of(day)

    if link and installments == 1 and card is None:
        bill = match_recurring(c, "expense", description, amount_cents, month)
        if bill:
            tx_id = insert_transaction(
                c,
                "expense",
                amount_cents,
                description,
                bill["category"],
                day,
                month,
                recurring_id=bill["id"],
                source=source,
                batch_id=batch_id,
                external_hash=external_hash,
            )
            return {"ids": [tx_id], "linked": "bill", "linked_name": bill["name"], "category": bill["category"]}
        debt = match_debt(c, description)
        if debt:
            tx_id = insert_transaction(
                c,
                "expense",
                amount_cents,
                description,
                "dividas",
                day,
                month,
                debt_id=debt["id"],
                source=source,
                batch_id=batch_id,
                external_hash=external_hash,
            )
            pay_debt_balance(c, debt["id"], amount_cents)
            return {"ids": [tx_id], "linked": "debt", "linked_name": debt["name"], "category": "dividas"}

    total_parts = max(1, installments)
    base, rest = divmod(amount_cents, total_parts)
    group = uuid.uuid4().hex if total_parts > 1 else None
    ids = []
    for index in range(first_installment - 1, total_parts):
        # O centavo que sobra da divisão fica na primeira parcela, como no banco.
        part = base + (rest if index == 0 else 0)
        offset = index - (first_installment - 1)
        budget = add_months(month, offset)
        invoice = None
        if card is not None:
            invoice = add_months(invoice_month_for(day, card["closing_day"], card["due_day"]), offset)
        # Parcela futura ou trazida de compra antiga já é compromisso, não escolha do mês.
        committed = 1 if index > 0 else 0
        part_day = day if offset == 0 else day_in_month(budget, day.day)
        ids.append(
            insert_transaction(
                c,
                "expense",
                part,
                description,
                category,
                part_day,
                budget,
                committed=committed,
                card_id=card["id"] if card is not None else None,
                invoice_month=invoice,
                group_id=group,
                installment_no=index + 1 if total_parts > 1 else None,
                installment_total=total_parts if total_parts > 1 else None,
                source=source,
                batch_id=batch_id,
                external_hash=external_hash if offset == 0 else None,
            )
        )
    return {"ids": ids, "linked": None, "category": category}


def add_income(
    c: sqlite3.Connection,
    amount_cents: int,
    description: str,
    day: date,
    *,
    source: str = "app",
    batch_id: str | None = None,
    external_hash: str | None = None,
) -> dict:
    ensure_started(c, config.today())
    month = month_of(day)
    income = match_recurring(c, "income", description, amount_cents, month)
    if income is None:
        # "recebi 4200" sem nome é o salário quando só existe uma renda e o valor bate.
        rows = c.execute("SELECT * FROM recurring WHERE active = 1 AND kind = 'income'").fetchall()
        if len(rows) == 1 and rows[0]["amount_cents"] * 0.8 <= amount_cents <= rows[0]["amount_cents"] * 1.2:
            if not c.execute(
                "SELECT 1 FROM transactions WHERE recurring_id = ? AND budget_month = ?", (rows[0]["id"], month)
            ).fetchone():
                income = rows[0]
    tx_id = insert_transaction(
        c,
        "income",
        amount_cents,
        description,
        "renda",
        day,
        month,
        recurring_id=income["id"] if income else None,
        source=source,
        batch_id=batch_id,
        external_hash=external_hash,
    )
    return {
        "ids": [tx_id],
        "linked": "income" if income else None,
        "linked_name": income["name"] if income else None,
        "category": "renda",
    }


def insert_transaction(
    c: sqlite3.Connection, kind: str, amount: int, description: str, category: str, day: date, budget: str, **extra
) -> int:
    fields = {
        "kind": kind,
        "amount_cents": amount,
        "description": description,
        "category": category,
        "date": day.isoformat(),
        "budget_month": budget,
        **extra,
    }
    columns = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    return c.execute(f"INSERT INTO transactions ({columns}) VALUES ({marks})", tuple(fields.values())).lastrowid


def pay_debt_balance(c: sqlite3.Connection, debt_id: int, amount: int) -> None:
    debt = c.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    if debt is None:
        return
    balance = max(0, debt["balance_cents"] - amount)
    c.execute(
        "UPDATE debts SET balance_cents = ?, active = ?, overdue = 0 WHERE id = ?",
        (balance, 0 if balance == 0 else 1, debt_id),
    )


def delete_transaction(c: sqlite3.Connection, tx_id: int) -> list[dict]:
    """Apaga o lançamento e, se for parcelado, a compra inteira. Devolve o saldo da
    dívida ao estado anterior, para que desfazer seja mesmo desfazer."""
    row = c.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if row is None:
        return []
    rows = (
        c.execute("SELECT * FROM transactions WHERE group_id = ?", (row["group_id"],)).fetchall()
        if row["group_id"]
        else [row]
    )
    removed = []
    for r in rows:
        if r["debt_id"]:
            c.execute(
                "UPDATE debts SET balance_cents = balance_cents + ?, active = 1 WHERE id = ?",
                (r["amount_cents"], r["debt_id"]),
            )
        c.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
        removed.append(dict(r))
    return removed


def last_transaction(c: sqlite3.Connection) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()


def set_category(c: sqlite3.Connection, tx_id: int, category: str) -> None:
    """Corrigir uma vez ensina para sempre: o próximo "ifood" já vem certo."""
    row = c.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if row is None:
        return
    if row["group_id"]:
        c.execute("UPDATE transactions SET category = ? WHERE group_id = ?", (category, row["group_id"]))
    else:
        c.execute("UPDATE transactions SET category = ? WHERE id = ?", (category, tx_id))
    merchant = merchant_key(row["description"])
    if merchant:
        c.execute(
            "INSERT INTO merchant_categories (merchant, category) VALUES (?, ?) ON CONFLICT(merchant) DO UPDATE SET category = excluded.category",
            (merchant, category),
        )


def merchant_key(description: str) -> str:
    return " ".join(re.findall(r"[a-z]{3,}", normalize(description))[:2])


def mark_paid(
    c: sqlite3.Connection, item_type: str, item_id: int, month: str, today: date, amount_cents: int | None = None
) -> str | None:
    """Botão "Paguei" para conta, fatura ou dívida. Devolve o nome do que foi pago."""
    ensure_started(c, today)
    if item_type == "invoice":
        card = c.execute("SELECT * FROM cards WHERE id = ?", (item_id,)).fetchone()
        if card is None:
            return None
        c.execute(
            "INSERT OR IGNORE INTO invoice_payments (card_id, invoice_month, paid_at) VALUES (?, ?, ?)",
            (item_id, month, today.isoformat()),
        )
        return f"Fatura {card['name']}"
    if item_type == "bill":
        bill = c.execute("SELECT * FROM recurring WHERE id = ?", (item_id,)).fetchone()
        if bill is None:
            return None
        if not c.execute(
            "SELECT 1 FROM transactions WHERE recurring_id = ? AND budget_month = ?", (item_id, month)
        ).fetchone():
            insert_transaction(
                c,
                "expense",
                amount_cents or bill["amount_cents"],
                bill["name"],
                bill["category"],
                today,
                month,
                recurring_id=item_id,
            )
        return bill["name"]
    if item_type == "debt":
        debt = c.execute("SELECT * FROM debts WHERE id = ?", (item_id,)).fetchone()
        if debt is None:
            return None
        if not c.execute(
            "SELECT 1 FROM transactions WHERE debt_id = ? AND budget_month = ?", (item_id, month)
        ).fetchone():
            amount = amount_cents or min(debt["min_payment_cents"], debt["balance_cents"])
            insert_transaction(c, "expense", amount, debt["name"], "dividas", today, month, debt_id=item_id)
            pay_debt_balance(c, item_id, amount)
        return debt["name"]
    return None


def set_opening_invoice(c: sqlite3.Connection, card_id: int, amount_cents: int, today: date) -> int:
    """A fatura que já existe ao começar: é compromisso do mês em que vence."""
    card = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    invoice = invoice_month_for(today, card["closing_day"], card["due_day"])
    ensure_started(c, today)
    c.execute(
        "DELETE FROM transactions WHERE card_id = ? AND source = 'opening' AND invoice_month = ?", (card_id, invoice)
    )
    return insert_transaction(
        c,
        "expense",
        amount_cents,
        f"Saldo inicial {card['name']}",
        "outros",
        today,
        invoice,
        committed=1,
        card_id=card_id,
        invoice_month=invoice,
        source="opening",
    )


def add_existing_installments(
    c: sqlite3.Connection,
    description: str,
    part_cents: int,
    paid_so_far: int,
    total: int,
    today: date,
    card: sqlite3.Row | None = None,
) -> list[int]:
    """Parcelas de compras antigas que ainda vão cair: 'TV 8 de 10, R$ 120'."""
    ensure_started(c, today)
    ids, group = [], uuid.uuid4().hex
    month = month_of(today)
    invoice = invoice_month_for(today, card["closing_day"], card["due_day"]) if card is not None else None
    for offset, number in enumerate(range(paid_so_far + 1, total + 1)):
        budget = add_months(month, offset)
        ids.append(
            insert_transaction(
                c,
                "expense",
                part_cents,
                description,
                guess_category(description, learned_categories(c)),
                today if offset == 0 else day_in_month(budget, today.day),
                budget,
                committed=1,
                card_id=card["id"] if card is not None else None,
                invoice_month=add_months(invoice, offset) if invoice else None,
                group_id=group,
                installment_no=number,
                installment_total=total,
                source="opening",
            )
        )
    return ids


def accrue_debt_interest(c: sqlite3.Connection, today: date) -> int:
    """Aplica um mês de juros ao saldo. Quem chama garante que roda uma vez por mês.
    Dívida recém-cadastrada fica de fora: o saldo informado já está atualizado."""
    total = 0
    for d in c.execute("SELECT * FROM debts WHERE active = 1 AND monthly_rate > 0").fetchall():
        if (today - date.fromisoformat(d["created_at"][:10])).days < 20:
            continue
        interest = round(d["balance_cents"] * d["monthly_rate"] / 100)
        total += interest
        c.execute("UPDATE debts SET balance_cents = balance_cents + ? WHERE id = ?", (interest, d["id"]))
    return total


def create_pause(c: sqlite3.Connection, item: str, amount_cents: int, installments: int = 1, hours: int = 24) -> int:
    created = config.now()
    return c.execute(
        "INSERT INTO pauses (item, amount_cents, installments, created_at, remind_at) VALUES (?, ?, ?, ?, ?)",
        (item, amount_cents, installments, created.isoformat(), (created + timedelta(hours=hours)).isoformat()),
    ).lastrowid


def assign_card(c: sqlite3.Connection, tx_id: int, card_id: int) -> None:
    """Liga ao cartão um gasto já lançado ("no cartão", quando há mais de um)."""
    row = c.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    card = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or card is None:
        return
    rows = (
        c.execute("SELECT * FROM transactions WHERE group_id = ? ORDER BY id", (row["group_id"],)).fetchall()
        if row["group_id"]
        else [row]
    )
    first = invoice_month_for(date.fromisoformat(rows[0]["date"]), card["closing_day"], card["due_day"])
    for offset, r in enumerate(rows):
        c.execute(
            "UPDATE transactions SET card_id = ?, invoice_month = ? WHERE id = ?",
            (card_id, add_months(first, offset), r["id"]),
        )


def resolve_pause(c: sqlite3.Connection, pause_id: int, status: str, today: date) -> sqlite3.Row | None:
    pause = c.execute("SELECT * FROM pauses WHERE id = ?", (pause_id,)).fetchone()
    if pause is None or pause["status"] != "waiting":
        return None
    c.execute("UPDATE pauses SET status = ? WHERE id = ?", (status, pause_id))
    if status == "bought":
        add_expense(
            c,
            pause["amount_cents"],
            pause["item"],
            today,
            installments=pause["installments"],
            source="pause",
            link=False,
        )
    return pause


def zero_day(c: sqlite3.Connection, day: date) -> None:
    ensure_started(c, config.today())
    c.execute("INSERT OR IGNORE INTO zero_days (date) VALUES (?)", (day.isoformat(),))
