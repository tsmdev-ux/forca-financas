"""Operações com validação, usadas igualmente pelo app, pelo bot e pelo agente."""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from . import config, db, finance, ledger, parser
from .finance import brl, month_of


class Invalid(ValueError):
    """Erro com mensagem que pode ser mostrada para a pessoa."""


def _day(value: int) -> int:
    value = int(value)
    if not 1 <= value <= 31:
        raise Invalid("O dia precisa estar entre 1 e 31.")
    return value


def valid_amount(value: int, allow_zero: bool = False) -> int:
    value = int(value)
    if value < 0 or (value == 0 and not allow_zero):
        raise Invalid("O valor precisa ser maior que zero.")
    return value


def _name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise Invalid("Falta o nome.")
    return value[:80]


def add_recurring(
    c: sqlite3.Connection, kind: str, name: str, amount_cents: int, day: int, category: str | None = None
) -> int:
    if kind not in ("income", "expense"):
        raise Invalid("Tipo inválido.")
    ledger.ensure_started(c, config.today())
    category = "renda" if kind == "income" else (category or parser.guess_category(name))
    if category == "outros":
        category = "contas"
    return c.execute(
        "INSERT INTO recurring (kind, name, amount_cents, day, category) VALUES (?, ?, ?, ?, ?)",
        (kind, _name(name), valid_amount(amount_cents), _day(day), category),
    ).lastrowid


def update_recurring(c: sqlite3.Connection, item_id: int, name: str, amount_cents: int, day: int) -> None:
    c.execute(
        "UPDATE recurring SET name = ?, amount_cents = ?, day = ? WHERE id = ?",
        (_name(name), valid_amount(amount_cents), _day(day), item_id),
    )


def remove_recurring(c: sqlite3.Connection, item_id: int) -> None:
    c.execute("UPDATE recurring SET active = 0 WHERE id = ?", (item_id,))


def add_card(c: sqlite3.Connection, name: str, closing_day: int, due_day: int, limit_cents: int | None = None) -> int:
    ledger.ensure_started(c, config.today())
    return c.execute(
        "INSERT INTO cards (name, closing_day, due_day, limit_cents) VALUES (?, ?, ?, ?)",
        (_name(name), _day(closing_day), _day(due_day), valid_amount(limit_cents, True) if limit_cents else None),
    ).lastrowid


def update_card(
    c: sqlite3.Connection, card_id: int, name: str, closing_day: int, due_day: int, limit_cents: int | None = None
) -> None:
    c.execute(
        "UPDATE cards SET name = ?, closing_day = ?, due_day = ?, limit_cents = ? WHERE id = ?",
        (
            _name(name),
            _day(closing_day),
            _day(due_day),
            valid_amount(limit_cents, True) if limit_cents else None,
            card_id,
        ),
    )


def remove_card(c: sqlite3.Connection, card_id: int) -> None:
    c.execute("UPDATE cards SET active = 0 WHERE id = ?", (card_id,))


def add_debt(
    c: sqlite3.Connection,
    name: str,
    balance_cents: int,
    monthly_rate: float,
    min_payment_cents: int,
    due_day: int,
    overdue: bool = False,
) -> int:
    rate = float(monthly_rate)
    if not 0 <= rate <= 100:
        raise Invalid("A taxa precisa ser ao mês, entre 0 e 100%.")
    ledger.ensure_started(c, config.today())
    return c.execute(
        "INSERT INTO debts (name, balance_cents, monthly_rate, min_payment_cents, due_day, overdue) VALUES (?, ?, ?, ?, ?, ?)",
        (
            _name(name),
            valid_amount(balance_cents),
            rate,
            valid_amount(min_payment_cents, True),
            _day(due_day),
            1 if overdue else 0,
        ),
    ).lastrowid


def update_debt(
    c: sqlite3.Connection,
    debt_id: int,
    name: str,
    balance_cents: int,
    monthly_rate: float,
    min_payment_cents: int,
    due_day: int,
    overdue: bool,
) -> None:
    rate = float(monthly_rate)
    if not 0 <= rate <= 100:
        raise Invalid("A taxa precisa ser ao mês, entre 0 e 100%.")
    balance = valid_amount(balance_cents, True)
    c.execute(
        "UPDATE debts SET name = ?, balance_cents = ?, monthly_rate = ?, min_payment_cents = ?, due_day = ?, overdue = ?, active = ? WHERE id = ?",
        (
            _name(name),
            balance,
            rate,
            valid_amount(min_payment_cents, True),
            _day(due_day),
            1 if overdue else 0,
            1 if balance > 0 else 0,
            debt_id,
        ),
    )


def remove_debt(c: sqlite3.Connection, debt_id: int) -> None:
    c.execute("UPDATE debts SET active = 0 WHERE id = ?", (debt_id,))


def set_category_budget(c: sqlite3.Connection, category: str, limit_cents: int) -> None:
    check_category(c, category)
    if limit_cents <= 0:
        c.execute("DELETE FROM category_budgets WHERE category = ?", (category,))
        return
    c.execute(
        "INSERT INTO category_budgets (category, limit_cents) VALUES (?, ?) ON CONFLICT(category) DO UPDATE SET limit_cents = excluded.limit_cents",
        (category, limit_cents),
    )


def check_category(c: sqlite3.Connection, key: str) -> None:
    if not c.execute("SELECT 1 FROM categories WHERE key = ? AND active = 1", (key,)).fetchone():
        names = ", ".join(r["key"] for r in c.execute("SELECT key FROM categories WHERE active = 1"))
        raise Invalid(f"Categoria desconhecida. As que existem: {names}.")


def add_category(c: sqlite3.Connection, label: str, icon: str = "dot") -> str:
    label = _name(label)[:30]
    key = "-".join(re.findall(r"[a-z0-9]+", parser.normalize(label)))[:30]
    if not key or key in parser.SYSTEM_CATEGORIES:
        raise Invalid("Escolha outro nome para a categoria.")
    icon = (icon or "dot").strip()[:20] or "dot"
    existing = c.execute("SELECT * FROM categories WHERE key = ?", (key,)).fetchone()
    if existing and existing["active"]:
        raise Invalid(f"A categoria {existing['label']} já existe.")
    c.execute(
        "INSERT INTO categories (key, label, icon, builtin) VALUES (?, ?, ?, 0) ON CONFLICT(key) DO UPDATE SET label = excluded.label, icon = excluded.icon, active = 1",
        (key, label, icon),
    )
    # O próprio nome já ensina: "pilates 90" cai em Pilates.
    c.execute(
        "INSERT OR REPLACE INTO merchant_categories (merchant, category) VALUES (?, ?)", (parser.normalize(label), key)
    )
    return key


def update_category(c: sqlite3.Connection, key: str, label: str, icon: str) -> None:
    check_category(c, key)
    c.execute(
        "UPDATE categories SET label = ?, icon = ? WHERE key = ?",
        (_name(label)[:30], (icon or "dot").strip()[:20] or "dot", key),
    )


def remove_category(c: sqlite3.Connection, key: str) -> int:
    """Os gastos não somem: passam para Outros."""
    if key in parser.SYSTEM_CATEGORIES:
        raise Invalid("Essa categoria não pode ser removida.")
    check_category(c, key)
    moved = c.execute("UPDATE transactions SET category = 'outros' WHERE category = ?", (key,)).rowcount
    c.execute("DELETE FROM category_budgets WHERE category = ?", (key,))
    c.execute("DELETE FROM merchant_categories WHERE category = ?", (key,))
    c.execute("UPDATE categories SET active = 0 WHERE key = ?", (key,))
    return moved


def _due_month(value: str | None) -> str | None:
    if not value:
        return None
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise Invalid("O prazo precisa ser um mês, como 2027-06.")
    return value


def _monthly_for(target: int, saved: int, due: str | None, monthly: int | None, today: date) -> int:
    """Sem valor mensal informado, divide o que falta pelos meses até o prazo."""
    if monthly:
        return valid_amount(monthly)
    if not due:
        return 0
    year, mon = map(int, due.split("-"))
    months = max(1, (year * 12 + mon) - (today.year * 12 + today.month) + 1)
    return -(-max(0, target - saved) // months)


def add_goal(
    c: sqlite3.Connection, name: str, target_cents: int, due_month: str | None = None, monthly_cents: int | None = None
) -> int:
    due = _due_month(due_month)
    target = valid_amount(target_cents)
    ledger.ensure_started(c, config.today())
    return c.execute(
        "INSERT INTO goals (name, target_cents, due_month, monthly_cents) VALUES (?, ?, ?, ?)",
        (_name(name), target, due, _monthly_for(target, 0, due, monthly_cents, config.today())),
    ).lastrowid


def update_goal(
    c: sqlite3.Connection, goal_id: int, name: str, target_cents: int, due_month: str | None, monthly_cents: int | None
) -> None:
    due = _due_month(due_month)
    target = valid_amount(target_cents)
    saved = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ?", (goal_id,)
    ).fetchone()["t"]
    c.execute(
        "UPDATE goals SET name = ?, target_cents = ?, due_month = ?, monthly_cents = ? WHERE id = ?",
        (_name(name), target, due, _monthly_for(target, saved, due, monthly_cents, config.today()), goal_id),
    )


def remove_goal(c: sqlite3.Connection, goal_id: int) -> None:
    c.execute("UPDATE goals SET active = 0 WHERE id = ?", (goal_id,))


def deposit_goal(c: sqlite3.Connection, goal_id: int, amount_cents: int, day: date) -> int:
    """Valor negativo é retirada: tirar da reserva é normal, mas não mais do que há nela."""
    goal = c.execute("SELECT * FROM goals WHERE id = ? AND active = 1", (goal_id,)).fetchone()
    if goal is None:
        raise Invalid("Meta não encontrada.")
    if amount_cents == 0:
        raise Invalid("O valor precisa ser diferente de zero.")
    saved = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ?", (goal_id,)
    ).fetchone()["t"]
    if saved + amount_cents < 0:
        raise Invalid(f"Essa meta só tem {brl(saved)} guardados.")
    ledger.ensure_started(c, config.today())
    return c.execute(
        "INSERT INTO goal_deposits (goal_id, amount_cents, date) VALUES (?, ?, ?)",
        (goal_id, amount_cents, day.isoformat()),
    ).lastrowid


def find_goal(c: sqlite3.Connection, hint: str) -> sqlite3.Row | None:
    goals = c.execute("SELECT * FROM goals WHERE active = 1").fetchall()
    words = ledger.match_words(hint)
    if words:
        for g in goals:
            if ledger.match_words(g["name"]) & words:
                return g
        return None
    return goals[0] if len(goals) == 1 else None


def set_debt_plan(c: sqlite3.Connection, extra_cents: int | None, strategy: str | None) -> None:
    if extra_cents is not None:
        db.set_setting(c, "debt_extra_cents", str(valid_amount(extra_cents, True)))
    if strategy is not None:
        if strategy not in ("avalanche", "snowball"):
            raise Invalid("Estratégia inválida.")
        db.set_setting(c, "debt_strategy", strategy)


def update_transaction(
    c: sqlite3.Connection, tx_id: int, description: str, amount_cents: int, day: date, category: str
) -> None:
    row = c.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if row is None:
        raise Invalid("Lançamento não encontrado.")
    check_category(c, category)
    if row["category"] != category:
        ledger.set_category(c, tx_id, category)
    if row["debt_id"] and amount_cents != row["amount_cents"]:
        c.execute(
            "UPDATE debts SET balance_cents = MAX(0, balance_cents - ?) WHERE id = ?",
            (amount_cents - row["amount_cents"], row["debt_id"]),
        )
    budget = row["budget_month"] if row["installment_no"] else month_of(day)
    c.execute(
        "UPDATE transactions SET description = ?, amount_cents = ?, date = ?, budget_month = ? WHERE id = ?",
        (_name(description), valid_amount(amount_cents), day.isoformat(), budget, tx_id),
    )


# ---------- captura em texto livre ----------


def looks_too_big(c: sqlite3.Connection, amount_cents: int) -> bool:
    """Um zero a mais estraga o mês inteiro: valor fora da realidade pede confirmação."""
    income = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM recurring WHERE active = 1 AND kind = 'income'"
    ).fetchone()["t"]
    return amount_cents > max(income * 3, 2_000_000)


def capture(c: sqlite3.Connection, text: str, today: date, source: str, confirmed: bool = False) -> dict | None:
    """Tenta registrar sem IA. None significa "não é um lançamento simples"."""
    cards = tuple(r["name"] for r in c.execute("SELECT name FROM cards WHERE active = 1"))
    parsed = parser.parse(text, today, cards, ledger.learned_categories(c))
    if parsed is None:
        return None
    if parsed.kind == "zero_day":
        ledger.zero_day(c, today)
        return {"type": "zero"}
    if not confirmed and looks_too_big(c, parsed.amount_cents):
        return {
            "type": "check",
            "amount_cents": parsed.amount_cents,
            "description": parsed.description,
            "date": parsed.date or today,
        }
    if parsed.kind == "goal_deposit":
        goal = find_goal(c, parsed.description)
        if goal is None:
            return None  # sem meta correspondente, a agente pergunta qual é
        deposit = deposit_goal(c, goal["id"], parsed.amount_cents, today)
        info = next(g for g in finance.goals_overview(c, today) if g["id"] == goal["id"])
        return {
            "type": "goal",
            "goal": goal["name"],
            "amount_cents": parsed.amount_cents,
            "deposit_id": deposit,
            "saved_cents": info["saved_cents"],
            "left_cents": info["left_cents"],
            "done": info["done"],
        }
    if parsed.kind.startswith("recurring_"):
        kind = "income" if parsed.kind == "recurring_income" else "expense"
        ledger.ensure_started(c, today)
        add_recurring(c, kind, parsed.description, parsed.amount_cents, parsed.installments)
        return {
            "type": "recurring",
            "kind": kind,
            "description": parsed.description,
            "amount_cents": parsed.amount_cents,
            "day": parsed.installments,
        }
    if parsed.kind == "income":
        result = ledger.add_income(c, parsed.amount_cents, parsed.description, parsed.date, source=source)
        return {
            "type": "income",
            "amount_cents": parsed.amount_cents,
            "description": parsed.description,
            "date": parsed.date,
            **result,
        }
    card = ledger.find_card(c, parsed.card_hint)
    result = ledger.add_expense(
        c,
        parsed.amount_cents,
        parsed.description,
        parsed.date,
        installments=parsed.installments,
        card=card,
        source=source,
    )
    return {
        "type": "expense",
        "amount_cents": parsed.amount_cents,
        "description": parsed.description,
        "date": parsed.date,
        "installments": parsed.installments,
        "card": card["name"] if card is not None else None,
        "needs_card": parsed.card_hint == "*" and card is None,
        **result,
    }


def goal_text(r: dict) -> str:
    if r["done"]:
        return f"Meta {r['goal']} concluída, com {brl(r['saved_cents'])} guardados. Parabéns!"
    return f"Guardado: {brl(r['amount_cents'])} em {r['goal']}. Já são {brl(r['saved_cents'])}; faltam {brl(r['left_cents'])}."


def feedback(c: sqlite3.Connection, today: date, spent_day: date) -> str:
    """A frase depois de registrar. É aqui que o gasto vira consciência, na hora."""
    now = finance.today_status(c, today)
    if now.status == "starting":
        return f"Registrado. Seu limite diário começa em 1º de {finance.next_month_name(today)}."
    if now.status == "setup":
        return "Falta sua renda para eu calcular o limite do dia. Mande /comecar e eu pergunto o que falta."
    if now.status == "broken":
        return f"O mês já está {brl(-now.budget.remaining)} no negativo. Vale cortar tudo que puder esperar."
    if spent_day != today:
        return (
            f"Lançado em {spent_day.strftime('%d/%m')}. Com isso, hoje você pode gastar {brl(max(0, now.left_today))}."
        )
    if now.budget.remaining < 0:
        return (
            f"O mês passou {brl(-now.budget.remaining)} do que cabia. A partir de agora, cada gasto sai do mês que vem."
        )
    if now.left_today < 0:
        return (
            f"Passou {brl(-now.left_today)} do limite de hoje. "
            f"Para o mês fechar, seu limite de amanhã cai para {brl(now.tomorrow)}."
        )
    if now.left_today == 0:
        return f"Limite de hoje zerado. Amanhã você tem {brl(now.tomorrow)}."
    return f"Ainda cabe {brl(now.left_today)} hoje."


def category_alert(c: sqlite3.Connection, category: str, today: date) -> str | None:
    """Avisa uma vez por mês ao chegar em 80% e ao passar de 100% de um limite."""
    limit = c.execute("SELECT limit_cents FROM category_budgets WHERE category = ?", (category,)).fetchone()
    if limit is None:
        return None
    month = month_of(today)
    label = db.category_label(category)
    spent = next((r["spent_cents"] for r in finance.categories_for(c, month) if r["category"] == category), 0)
    ratio = spent / limit["limit_cents"]
    for threshold, text in (
        (1.0, f"Você passou do limite de {label}: {brl(spent)} de {brl(limit['limit_cents'])}."),
        (
            0.8,
            f"{label.capitalize()} já está em {round(ratio * 100)}% do limite ({brl(spent)} de {brl(limit['limit_cents'])}).",
        ),
    ):
        if ratio >= threshold:
            key = f"cat:{category}:{month}:{threshold}"
            if c.execute("SELECT 1 FROM nudge_log WHERE key = ?", (key,)).fetchone():
                return None
            c.execute("INSERT INTO nudge_log (key, sent_at) VALUES (?, ?)", (key, today.isoformat()))
            return text
    return None


def assessment_text(item: str, a: dict) -> str:
    lines = {
        "yes": f"{item}: <b>cabe</b>.",
        "wait": f"{item}: <b>eu esperaria</b>.",
        "no": f"{item}: <b>não cabe neste mês</b>.",
    }
    out = [lines[a["verdict"]]]
    if a["installments"] > 1:
        out.append(
            f"{a['installments']}x de {brl(a['first_payment_cents'])}, comprometendo os próximos {a['future_months_committed']} meses."
        )
    if a["days_of_allowance"] is not None and a["days_of_allowance"] >= 1:
        out.append(f"Equivale a {str(a['days_of_allowance']).replace('.', ',')} dias do seu limite.")
    if a["remaining_after_cents"] >= 0:
        out.append(f"Seu limite diário iria de {brl(a['current_daily_cents'])} para {brl(a['new_daily_cents'])}.")
    else:
        out.append(f"O mês fecharia {brl(-a['remaining_after_cents'])} no negativo.")
    if a["debt_interest_12m_cents"] > 0:
        out.append(
            f"Esse valor em dívida a {str(a['top_debt_rate']).replace('.', ',')}% ao mês vira {brl(a['debt_interest_12m_cents'])} de juros em um ano."
        )
    return "\n".join(out)
