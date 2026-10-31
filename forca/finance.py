"""As contas do app. Tudo que aparece na tela ou no Telegram sai daqui.

O modelo: cada real pertence ao orçamento de um mês (`budget_month`).
  sobra = renda − contas fixas − dívidas − parcelas antigas − déficit do mês anterior
  hoje  = (sobra − gasto até ontem) / dias restantes − gasto de hoje
Compra no cartão pesa no mês em que foi feita, não no mês da fatura; pagar a fatura
é só transferência. Sem isso, a fatura vira surpresa e o número do dia mente.
"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from . import config, db
from .parser import DISCRETIONARY


def month_of(d: date) -> str:
    return d.strftime("%Y-%m")


def add_months(month: str, n: int) -> str:
    year, mon = map(int, month.split("-"))
    total = year * 12 + (mon - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def days_in(month: str) -> int:
    year, mon = map(int, month.split("-"))
    return calendar.monthrange(year, mon)[1]


def day_in_month(month: str, day: int) -> date:
    """Dia 31 em fevereiro cai no último dia, como os bancos fazem."""
    year, mon = map(int, month.split("-"))
    return date(year, mon, min(day, calendar.monthrange(year, mon)[1]))


def invoice_month_for(purchase: date, closing_day: int, due_day: int) -> str:
    """Mês em que vence a fatura que recebe uma compra feita em `purchase`."""
    closing_month = month_of(purchase)
    if purchase.day >= min(closing_day, days_in(closing_month)):
        closing_month = add_months(closing_month, 1)
    return add_months(closing_month, 1) if due_day <= closing_day else closing_month


# ---------- mês ----------


@dataclass
class MonthBudget:
    month: str
    income: int
    fixed: int
    debts: int
    goals: int
    committed: int
    carry: int
    available: int
    spent: int
    remaining: int
    income_is_estimate: bool


def _recurring_totals(c: sqlite3.Connection, month: str) -> tuple[int, int, bool]:
    """Valor real quando já foi lançado; previsto enquanto não foi."""
    income = fixed = 0
    has_estimate = False
    for item in c.execute("SELECT * FROM recurring WHERE active = 1"):
        row = c.execute(
            "SELECT SUM(amount_cents) AS total FROM transactions WHERE recurring_id = ? AND budget_month = ?",
            (item["id"], month),
        ).fetchone()
        paid = row["total"]
        if item["kind"] == "income":
            income += paid if paid is not None else item["amount_cents"]
            has_estimate = has_estimate or paid is None
        else:
            fixed += paid if paid is not None else item["amount_cents"]
    return income, fixed, has_estimate


def _debt_total(c: sqlite3.Connection, month: str) -> int:
    """O maior entre o combinado (mínimos + extra) e o que já foi pago no mês."""
    planned = sum(r["min_payment_cents"] for r in c.execute("SELECT min_payment_cents FROM debts WHERE active = 1"))
    planned += int(db.get_setting(c, "debt_extra_cents", "0") or 0)
    paid = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE debt_id IS NOT NULL AND budget_month = ?",
        (month,),
    ).fetchone()["t"]
    return max(planned, paid)


def _goal_deposits(c: sqlite3.Connection, month: str) -> int:
    return c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE substr(date, 1, 7) = ?", (month,)
    ).fetchone()["t"]


def _goal_total(c: sqlite3.Connection, month: str) -> int:
    """Mês que passou conta o que foi guardado; do mês atual em diante, também o combinado."""
    deposited = max(0, _goal_deposits(c, month))
    if month < month_of(config.today()):
        return deposited
    planned = 0
    for g in c.execute(
        "SELECT id, target_cents, monthly_cents FROM goals WHERE active = 1 AND monthly_cents > 0"
    ).fetchall():
        saved = c.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ?", (g["id"],)
        ).fetchone()["t"]
        this_month = c.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ? AND substr(date, 1, 7) = ?",
            (g["id"], month),
        ).fetchone()["t"]
        planned += min(g["monthly_cents"], max(0, g["target_cents"] - saved + this_month))
    return max(planned, deposited)


def _month_core(c: sqlite3.Connection, month: str) -> tuple[int, int, int, int, int, int, bool]:
    income, fixed, estimate = _recurring_totals(c, month)
    extra_income = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE kind = 'income' AND recurring_id IS NULL AND budget_month = ?",
        (month,),
    ).fetchone()["t"]
    income += extra_income
    debts = _debt_total(c, month)
    committed = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE kind = 'expense' AND committed = 1 AND recurring_id IS NULL AND debt_id IS NULL AND budget_month = ?",
        (month,),
    ).fetchone()["t"]
    spent = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE kind = 'expense' AND committed = 0 AND recurring_id IS NULL AND debt_id IS NULL AND budget_month = ?",
        (month,),
    ).fetchone()["t"]
    return income, fixed, debts, committed, spent, extra_income, estimate


def _carry_into(c: sqlite3.Connection, month: str) -> int:
    """Déficit herdado. Só o estouro vem junto: uma sobra no papel pode não estar
    na conta, então nunca aumenta o que o app diz que dá para gastar."""
    started = db.get_setting(c, "started_month")
    if not started or month <= started:
        return 0
    # Mês iniciado pela metade não gera déficit: renda e contas dele vieram de antes do app.
    started_date = db.get_setting(c, "started_date")
    first = add_months(started, 1) if started_date and started_date[8:10] != "01" else started
    cursor = max(first, add_months(month, -12))
    carry = 0
    while cursor < month:
        income, fixed, debts, committed, spent, _, _ = _month_core(c, cursor)
        balance = income - fixed - debts - committed - carry - spent - max(0, _goal_deposits(c, cursor))
        carry = -balance if balance < 0 else 0
        cursor = add_months(cursor, 1)
    return carry


def month_budget(c: sqlite3.Connection, month: str) -> MonthBudget:
    income, fixed, debts, committed, spent, _, estimate = _month_core(c, month)
    carry = _carry_into(c, month)
    goals = _goal_total(c, month)
    available = income - fixed - debts - goals - committed - carry
    return MonthBudget(
        month, income, fixed, debts, goals, committed, carry, available, spent, available - spent, estimate
    )


def _spent_on(c: sqlite3.Connection, day: date) -> int:
    return c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE kind = 'expense' AND committed = 0 AND recurring_id IS NULL AND debt_id IS NULL AND date = ? AND budget_month = ?",
        (day.isoformat(), month_of(day)),
    ).fetchone()["t"]


@dataclass
class Today:
    budget: MonthBudget
    days_left: int
    daily_allowance: int  # o limite de hoje, definido pela manhã
    spent_today: int
    left_today: int  # o que ainda cabe hoje; negativo = passou
    tomorrow: int  # como fica o limite de amanhã, no ritmo atual
    status: str  # setup | starting | ok | tight | over | broken


def today_status(c: sqlite3.Connection, today: date) -> Today:
    month = month_of(today)
    budget = month_budget(c, month)
    spent_today = _spent_on(c, today)
    days_left = days_in(month) - today.day + 1
    before_today = budget.spent - spent_today
    allowance = max(0, (budget.available - before_today) // days_left)
    left = allowance - spent_today
    tomorrow = max(0, budget.remaining // (days_left - 1)) if days_left > 1 else 0

    started = db.get_setting(c, "started_date")
    if budget.income == 0:
        status = "setup"
    elif started and started[:7] == month and started[8:10] != "01" and days_left <= 3:
        status = "starting"  # poucos dias de um mês já quase gasto: um limite aqui seria inventado
    elif budget.available <= 0:
        status = "broken"  # as contas do mês já não fecham antes de qualquer gasto
    elif budget.remaining <= 0 or left < 0:
        status = "over"
    else:
        ideal = budget.available // days_in(month)
        status = "tight" if allowance < ideal * 0.6 else "ok"
    return Today(budget, days_left, allowance, spent_today, left, tomorrow, status)


_MONTH_NAMES = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


def month_name(month: str) -> str:
    return f"{_MONTH_NAMES[int(month[5:7]) - 1]} de {month[:4]}"


def next_month_name(today: date) -> str:
    return _MONTH_NAMES[int(add_months(month_of(today), 1)[5:7]) - 1]


# ---------- o que vence ----------


def upcoming(c: sqlite3.Connection, today: date, horizon_days: int = 35) -> list[dict]:
    """Contas, faturas e dívidas não pagas, incluindo as atrasadas, por data."""
    items: list[dict] = []
    month = month_of(today)
    months = [add_months(month, -1), month, add_months(month, 1)]
    started = db.get_setting(c, "started_month") or month
    limit = today + timedelta(days=horizon_days)
    # O que venceu antes de começar a usar o app não é atraso que o app possa afirmar.
    started_date = date.fromisoformat(db.get_setting(c, "started_date") or "0001-01-01")

    def in_window(due: date, m: str) -> bool:
        return m >= started and started_date <= due <= limit

    for r in c.execute("SELECT * FROM recurring WHERE active = 1 AND kind = 'expense'").fetchall():
        for m in months:
            due = day_in_month(m, r["day"])
            if not in_window(due, m):
                continue
            paid = c.execute(
                "SELECT 1 FROM transactions WHERE recurring_id = ? AND budget_month = ? LIMIT 1", (r["id"], m)
            ).fetchone()
            if not paid:
                items.append(
                    {
                        "type": "bill",
                        "id": r["id"],
                        "month": m,
                        "name": r["name"],
                        "amount_cents": r["amount_cents"],
                        "due": due,
                    }
                )

    for card in c.execute("SELECT * FROM cards WHERE active = 1").fetchall():
        for m in months:
            due = day_in_month(m, card["due_day"])
            if not in_window(due, m):
                continue
            if c.execute(
                "SELECT 1 FROM invoice_payments WHERE card_id = ? AND invoice_month = ?", (card["id"], m)
            ).fetchone():
                continue
            total = invoice_total(c, card["id"], m)
            if total > 0:
                items.append(
                    {
                        "type": "invoice",
                        "id": card["id"],
                        "month": m,
                        "name": f"Fatura {card['name']}",
                        "amount_cents": total,
                        "due": due,
                    }
                )

    for d in c.execute("SELECT * FROM debts WHERE active = 1 AND min_payment_cents > 0").fetchall():
        for m in months:
            due = day_in_month(m, d["due_day"])
            if not in_window(due, m):
                continue
            paid = c.execute(
                "SELECT 1 FROM transactions WHERE debt_id = ? AND budget_month = ? LIMIT 1", (d["id"], m)
            ).fetchone()
            if not paid:
                items.append(
                    {
                        "type": "debt",
                        "id": d["id"],
                        "month": m,
                        "name": d["name"],
                        "amount_cents": min(d["min_payment_cents"], d["balance_cents"]),
                        "due": due,
                    }
                )

    for item in items:
        item["days"] = (item["due"] - today).days
        item["due"] = item["due"].isoformat()
    items.sort(key=lambda i: i["due"])
    return items


# ---------- cartões ----------


def invoice_total(c: sqlite3.Connection, card_id: int, invoice_month: str) -> int:
    return c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE card_id = ? AND invoice_month = ? AND kind = 'expense'",
        (card_id, invoice_month),
    ).fetchone()["t"]


def cards_overview(c: sqlite3.Connection, today: date) -> list[dict]:
    result = []
    for card in c.execute("SELECT * FROM cards WHERE active = 1 ORDER BY name").fetchall():
        current = invoice_month_for(today, card["closing_day"], card["due_day"])
        months = [add_months(current, i) for i in range(6)]
        # A fatura que fechou e ainda não venceu também é a sua "próxima" conta a pagar.
        previous = add_months(current, -1)
        previous_open = (
            invoice_total(c, card["id"], previous) > 0
            and not c.execute(
                "SELECT 1 FROM invoice_payments WHERE card_id = ? AND invoice_month = ?", (card["id"], previous)
            ).fetchone()
        )
        if previous_open:
            months.insert(0, previous)
        invoices = [{"month": m, "total_cents": invoice_total(c, card["id"], m), "open": m == current} for m in months]

        closing = day_in_month(month_of(today), card["closing_day"])
        if closing <= today:
            closing = day_in_month(add_months(month_of(today), 1), card["closing_day"])
        future = c.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE card_id = ? AND invoice_month > ? AND kind = 'expense'",
            (card["id"], current),
        ).fetchone()["t"]
        result.append(
            {
                **dict(card),
                "invoices": invoices,
                "current_invoice_cents": invoice_total(c, card["id"], current),
                "future_committed_cents": future,
                "next_closing": closing.isoformat(),
                "days_to_closing": (closing - today).days,
                "best_day": closing.day % days_in(month_of(closing)) + 1,
            }
        )
    return result


# ---------- dívidas ----------


def simulate_debts(debts: list[dict], extra_cents: int, strategy: str = "avalanche", max_months: int = 360) -> dict:
    """Mês a mês: juros, depois mínimos, depois todo o resto no alvo da estratégia.
    O que uma dívida quitada liberava passa a ir para a próxima."""
    state = [dict(d, bal=d["balance_cents"]) for d in debts if d["balance_cents"] > 0]
    if not state:
        return {"months": 0, "total_interest_cents": 0, "timeline": [0], "payoff_order": [], "feasible": True}
    budget = sum(d["min_payment_cents"] for d in state) + max(0, extra_cents)

    def priority(d: dict) -> tuple:
        if strategy == "snowball":
            return (d["bal"], -d["monthly_rate"])
        return (-d["monthly_rate"], d["bal"])

    months = interest_total = 0
    order: list[dict] = []
    timeline = [sum(d["bal"] for d in state)]
    while any(d["bal"] > 0 for d in state):
        if months >= max_months:
            # Trinta anos pagando é, para quem está decidindo, "não termina".
            return {
                "months": None,
                "total_interest_cents": interest_total,
                "timeline": timeline[:25],
                "payoff_order": order,
                "feasible": False,
            }
        months += 1
        interest_this_month = 0
        for d in state:
            if d["bal"] > 0:
                interest = round(d["bal"] * d["monthly_rate"] / 100)
                d["bal"] += interest
                interest_this_month += interest
        interest_total += interest_this_month

        left = budget
        active = [d for d in state if d["bal"] > 0]
        for d in active:
            pay = min(d["min_payment_cents"], d["bal"], left)
            d["bal"] -= pay
            left -= pay
        for d in sorted([d for d in active if d["bal"] > 0], key=priority):
            pay = min(left, d["bal"])
            d["bal"] -= pay
            left -= pay
        for d in active:
            if d["bal"] == 0:
                order.append({"name": d["name"], "month": months})
        timeline.append(sum(d["bal"] for d in state))
    return {
        "months": months,
        "total_interest_cents": interest_total,
        "timeline": timeline,
        "payoff_order": order,
        "feasible": True,
    }


def debts_overview(c: sqlite3.Connection, today: date) -> dict:
    debts = [dict(r) for r in c.execute("SELECT * FROM debts WHERE active = 1").fetchall()]
    extra = int(db.get_setting(c, "debt_extra_cents", "0") or 0)
    strategy = db.get_setting(c, "debt_strategy", "avalanche") or "avalanche"
    plan = simulate_debts(debts, extra, strategy)
    other = simulate_debts(debts, extra, "snowball" if strategy == "avalanche" else "avalanche")
    for d in debts:
        d["monthly_interest_cents"] = round(d["balance_cents"] * d["monthly_rate"] / 100)
        d["never_ends"] = d["min_payment_cents"] <= d["monthly_interest_cents"] and d["balance_cents"] > 0

    # Atrasadas primeiro: juros de mora, nome sujo e cobrança custam mais que a taxa sugere.
    ordered = sorted(
        debts,
        key=lambda d: (
            (-d["overdue"], d["balance_cents"], -d["monthly_rate"])
            if strategy == "snowball"
            else (-d["overdue"], -d["monthly_rate"], d["balance_cents"])
        ),
    )
    free_date = None
    if plan["feasible"] and plan["months"]:
        free_month = add_months(month_of(today), plan["months"])
        free_date = free_month
    return {
        "debts": ordered,
        "total_cents": sum(d["balance_cents"] for d in debts),
        "monthly_interest_cents": sum(d["monthly_interest_cents"] for d in debts),
        "extra_cents": extra,
        "strategy": strategy,
        "plan": plan,
        "other_strategy": {"months": other["months"], "total_interest_cents": other["total_interest_cents"]},
        "free_month": free_date,
        "target": ordered[0]["name"] if ordered else None,
    }


# ---------- categorias, ritmo e hábitos ----------

_VARIABLE = "kind = 'expense' AND committed = 0 AND recurring_id IS NULL AND debt_id IS NULL"


def category_list(c: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT * FROM categories WHERE active = 1 ORDER BY builtin DESC, rowid")]


def categories_for(c: sqlite3.Connection, month: str) -> list[dict]:
    meta = {r["key"]: r for r in c.execute("SELECT * FROM categories")}
    limits = {r["category"]: r["limit_cents"] for r in c.execute("SELECT * FROM category_budgets")}
    spent = {
        r["category"]: r["t"]
        for r in c.execute(
            f"SELECT category, SUM(amount_cents) AS t FROM transactions WHERE {_VARIABLE} AND budget_month = ? GROUP BY category",
            (month,),
        )
    }
    previous = {
        r["category"]: r["t"]
        for r in c.execute(
            f"SELECT category, SUM(amount_cents) AS t FROM transactions WHERE {_VARIABLE} AND budget_month = ? GROUP BY category",
            (add_months(month, -1),),
        )
    }
    rows = [
        {
            "category": cat,
            "label": meta[cat]["label"] if cat in meta else cat.capitalize(),
            "icon": meta[cat]["icon"] if cat in meta else "dot",
            "spent_cents": spent.get(cat, 0),
            "limit_cents": limits.get(cat),
            "previous_cents": previous.get(cat, 0),
        }
        for cat in set(spent) | set(limits)
    ]
    rows.sort(key=lambda r: -r["spent_cents"])
    return rows


def _has_activity(c: sqlite3.Connection, month: str) -> bool:
    return (
        c.execute(f"SELECT 1 FROM transactions WHERE {_VARIABLE} AND budget_month = ? LIMIT 1", (month,)).fetchone()
        is not None
    )


def report(c: sqlite3.Connection, month: str, today: date) -> dict:
    """O relatório de um mês: números e frases prontas, todos calculados aqui."""
    b = month_budget(c, month)
    previous = add_months(month, -1)
    has_previous = _has_activity(c, previous)
    prev_budget = month_budget(c, previous) if has_previous else None
    rows = categories_for(c, month)
    for r in rows:
        r["delta_cents"] = r["spent_cents"] - r["previous_cents"] if has_previous else None

    elapsed = days_in(month) if month < month_of(today) else today.day
    top = [
        dict(r)
        for r in c.execute(
            f"SELECT id, description, amount_cents, category, date FROM transactions WHERE {_VARIABLE} AND budget_month = ? AND amount_cents > 0 ORDER BY amount_cents DESC LIMIT 5",
            (month,),
        )
    ]
    saved = _goal_deposits(c, month)

    history = []
    for offset in range(-5, 1):
        m = add_months(month, offset)
        if _has_activity(c, m) or m == month:
            item = month_budget(c, m)
            history.append(
                {
                    "month": m,
                    "spent_cents": item.spent,
                    "available_cents": item.available,
                    "saved_cents": _goal_deposits(c, m),
                }
            )

    insights: list[dict] = []
    if prev_budget is not None:
        delta = b.spent - prev_budget.spent
        if month == month_of(today):
            # Mês em andamento só é comparável até o mesmo dia.
            same_period = c.execute(
                f"SELECT COALESCE(SUM(amount_cents), 0) AS t FROM transactions WHERE {_VARIABLE} AND budget_month = ? AND CAST(substr(date, 9, 2) AS INTEGER) <= ?",
                (previous, today.day),
            ).fetchone()["t"]
            delta = b.spent - same_period
            when = f"até o dia {today.day}"
        else:
            when = "no mês"
        if delta > 0:
            insights.append({"tone": "warning", "text": f"Você gastou {brl(delta)} a mais que no mês anterior {when}."})
        elif delta < 0:
            insights.append({"tone": "good", "text": f"Você gastou {brl(-delta)} a menos que no mês anterior {when}."})
        grown = [r for r in rows if r["delta_cents"] and r["delta_cents"] > 0]
        if grown and month < month_of(today):
            worst = max(grown, key=lambda r: r["delta_cents"])
            insights.append(
                {
                    "tone": "neutral",
                    "text": f"{worst['label']} foi o que mais cresceu: {brl(worst['delta_cents'])} a mais.",
                }
            )
    past = [r for r in rows if r["limit_cents"] and r["spent_cents"] > r["limit_cents"]]
    if past:
        names = ", ".join(r["label"] for r in past[:3])
        insights.append({"tone": "warning", "text": f"Passou do limite em: {names}."})
    if saved > 0:
        insights.append({"tone": "good", "text": f"Você guardou {brl(saved)} neste mês."})

    return {
        "month": month,
        "is_current": month == month_of(today),
        "can_go_next": month < month_of(today),
        "income_cents": b.income,
        "fixed_cents": b.fixed,
        "debts_cents": b.debts,
        "goals_cents": b.goals,
        "committed_cents": b.committed,
        "carry_cents": b.carry,
        "available_cents": b.available,
        "spent_cents": b.spent,
        "remaining_cents": b.remaining,
        "income_is_estimate": b.income_is_estimate and month >= month_of(today),
        "previous_spent_cents": prev_budget.spent if prev_budget else None,
        "daily_average_cents": b.spent // max(1, elapsed),
        "categories": rows,
        "top_expenses": top,
        "saved_cents": saved,
        "history": history,
        "insights": insights[:3],
    }


# ---------- metas ----------


def goals_overview(c: sqlite3.Connection, today: date) -> list[dict]:
    month = month_of(today)
    result = []
    for g in c.execute("SELECT * FROM goals WHERE active = 1 ORDER BY id").fetchall():
        saved = c.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ?", (g["id"],)
        ).fetchone()["t"]
        this_month = c.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM goal_deposits WHERE goal_id = ? AND substr(date, 1, 7) = ?",
            (g["id"], month),
        ).fetchone()["t"]
        left = max(0, g["target_cents"] - saved)
        monthly = g["monthly_cents"]
        finish = None
        if left == 0:
            finish = month
        elif monthly > 0:
            # O mês atual conta enquanto a parcela dele não foi guardada.
            start = month if this_month < monthly else add_months(month, 1)
            finish = add_months(start, -(-left // monthly) - 1)
        on_time = None
        if g["due_month"] and left > 0:
            on_time = finish is not None and finish <= g["due_month"]
        deposits = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM goal_deposits WHERE goal_id = ? ORDER BY date DESC, id DESC LIMIT 10", (g["id"],)
            )
        ]
        result.append(
            {
                **dict(g),
                "saved_cents": saved,
                "left_cents": left,
                "done": left == 0,
                "this_month_cents": this_month,
                "due_this_month_cents": max(0, min(monthly, left + this_month) - this_month),
                "finish_month": finish,
                "on_time": on_time,
                "deposits": deposits,
            }
        )
    return result


def suggested_reserve(c: sqlite3.Connection) -> int:
    """Reserva de emergência: 3 meses do que não dá para deixar de pagar."""
    fixed = c.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS t FROM recurring WHERE active = 1 AND kind = 'expense'"
    ).fetchone()["t"]
    debts = c.execute("SELECT COALESCE(SUM(min_payment_cents), 0) AS t FROM debts WHERE active = 1").fetchone()["t"]
    return (fixed + debts) * 3


def pace_series(c: sqlite3.Connection, month: str, today: date) -> list[dict]:
    """Gasto acumulado por dia, para comparar com o ritmo que fecha o mês."""
    budget = month_budget(c, month)
    total_days = days_in(month)
    daily = {
        r["date"]: r["t"]
        for r in c.execute(
            f"SELECT date, SUM(amount_cents) AS t FROM transactions WHERE {_VARIABLE} AND budget_month = ? GROUP BY date",
            (month,),
        )
    }
    series, running = [], 0
    for day in range(1, total_days + 1):
        current = day_in_month(month, day)
        running += daily.get(current.isoformat(), 0)
        series.append(
            {
                "day": day,
                "spent_cents": running if current <= today else None,
                "ideal_cents": max(0, budget.available) * day // total_days,
            }
        )
    return series


def projected_month_end(c: sqlite3.Connection, today: date) -> int:
    """Quanto o mês fecha acima (+) ou abaixo (−) da sobra, se o ritmo continuar."""
    month = month_of(today)
    budget = month_budget(c, month)
    pace = budget.spent / max(1, today.day)
    return round(pace * days_in(month)) - budget.available


def risky_weekday(c: sqlite3.Connection, today: date, weeks: int = 8, min_occurrences: int = 4) -> dict | None:
    """Se hoje é o dia da semana em que uma categoria opcional costuma pesar."""
    since = (today - timedelta(weeks=weeks)).isoformat()
    placeholders = ",".join("?" for _ in DISCRETIONARY)
    rows = c.execute(
        f"SELECT date, category, amount_cents FROM transactions WHERE {_VARIABLE} AND date >= ? AND date < ? AND category IN ({placeholders})",
        (since, today.isoformat(), *sorted(DISCRETIONARY)),
    ).fetchall()
    best: dict | None = None
    by_category: dict[str, list] = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)
    for category, entries in by_category.items():
        same_day = [e for e in entries if date.fromisoformat(e["date"]).weekday() == today.weekday()]
        distinct = {e["date"] for e in same_day}
        if len(distinct) < min_occurrences:
            continue
        average = sum(e["amount_cents"] for e in same_day) // len(distinct)
        # Só é padrão se este dia pesa bem mais que a média dos outros dias com gasto.
        others = [e for e in entries if date.fromisoformat(e["date"]).weekday() != today.weekday()]
        other_days = {e["date"] for e in others}
        other_avg = sum(e["amount_cents"] for e in others) // max(1, len(other_days))
        if average < other_avg * 1.3:
            continue
        if best is None or average > best["average_cents"]:
            best = {"category": category, "average_cents": average, "occurrences": len(distinct)}
    return best


def streak(c: sqlite3.Connection, today: date) -> int:
    """Dias seguidos com o registro em dia. Hoje só conta depois de registrado,
    mas não quebra a sequência enquanto o dia não acabou."""
    logged = {
        r["date"]
        for r in c.execute(
            "SELECT DISTINCT date FROM transactions WHERE date >= ?", ((today - timedelta(days=400)).isoformat(),)
        )
    }
    logged |= {r["date"] for r in c.execute("SELECT date FROM zero_days")}
    count = 0
    cursor = today
    if cursor.isoformat() not in logged:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in logged:
        count += 1
        cursor -= timedelta(days=1)
    return count


def saved_by_pauses(c: sqlite3.Connection) -> int:
    return c.execute("SELECT COALESCE(SUM(amount_cents), 0) AS t FROM pauses WHERE status = 'skipped'").fetchone()["t"]


# ---------- freio de impulso ----------


def assess_purchase(c: sqlite3.Connection, today: date, amount_cents: int, installments: int = 1) -> dict:
    now = today_status(c, today)
    first = amount_cents // max(1, installments)
    days_of_allowance = round(first / now.daily_allowance, 1) if now.daily_allowance > 0 else None
    remaining_after = now.budget.remaining - first
    days_after = max(1, now.days_left)
    new_daily = max(0, remaining_after // days_after)
    debts = debts_overview(c, today)
    top_rate = max((d["monthly_rate"] for d in debts["debts"]), default=0)
    interest_12m = round(amount_cents * ((1 + top_rate / 100) ** 12 - 1)) if top_rate > 0 else 0

    if now.status in ("broken", "setup") or remaining_after < 0:
        verdict = "no"
    elif first > now.left_today and (days_of_allowance or 99) >= 2:
        verdict = "wait"
    elif top_rate >= 3 and amount_cents > now.daily_allowance:
        verdict = "wait"
    else:
        verdict = "yes"
    return {
        "verdict": verdict,
        "first_payment_cents": first,
        "installments": installments,
        "new_daily_cents": new_daily,
        "current_daily_cents": now.daily_allowance,
        "remaining_after_cents": remaining_after,
        "days_of_allowance": days_of_allowance,
        "top_debt_rate": top_rate,
        "debt_interest_12m_cents": interest_12m,
        "future_months_committed": max(0, installments - 1),
    }


# ---------- a próxima coisa certa a fazer ----------


def focus(c: sqlite3.Connection, today: date) -> dict | None:
    """Uma recomendação só, a mais urgente. Vinte painéis são o que faz a gente desistir."""
    now = today_status(c, today)
    if now.status == "starting":
        return None
    items = upcoming(c, today, 7)
    overdue = [i for i in items if i["days"] < 0]
    if overdue:
        worst = overdue[0]
        return {
            "tone": "critical",
            "title": f"{worst['name']} está atrasada",
            "body": f"Venceu há {-worst['days']} dia(s). Resolva esta antes de qualquer gasto opcional.",
        }
    debts = debts_overview(c, today)
    late = [d for d in debts["debts"] if d["overdue"]]
    if late:
        return {
            "tone": "critical",
            "title": f"Negocie {late[0]['name']} primeiro",
            "body": "Dívida em atraso custa mais que a taxa que aparece. Peça uma proposta de acordo antes de pagar qualquer outra coisa além do mínimo.",
        }
    if now.status == "broken":
        missing = -now.budget.available
        return {
            "tone": "critical",
            "title": "O mês não fecha ainda",
            "body": f"Faltam {brl(missing)} só para o que já é compromisso. Sem cortar uma conta fixa ou renegociar uma dívida, não há gasto seguro.",
        }
    stuck = [d for d in debts["debts"] if d["never_ends"]]
    if stuck:
        d = stuck[0]
        return {
            "tone": "warning",
            "title": f"{d['name']} não diminui",
            "body": f"Os juros são {brl(d['monthly_interest_cents'])} por mês, e o pagamento é {brl(d['min_payment_cents'])}. Nesse valor ela nunca acaba. Ela é a primeira a renegociar.",
        }
    if debts["debts"] and debts["monthly_interest_cents"] > 0:
        return {
            "tone": "neutral",
            "title": f"Próximo alvo: {debts['target']}",
            "body": f"Suas dívidas custam {brl(debts['monthly_interest_cents'])} de juros por mês. Todo real a mais aqui rende mais que qualquer investimento.",
        }
    over_pace = projected_month_end(c, today)
    if today.day >= 5 and now.budget.available > 0 and over_pace > now.budget.available * 0.1:
        return {
            "tone": "warning",
            "title": "O ritmo está acima do mês",
            "body": f"Se continuar assim, o mês fecha {brl(over_pace)} acima da sobra.",
        }
    return None


def brl(cents: int) -> str:
    sign = "−" if cents < 0 else ""
    cents = abs(cents)
    whole, frac = divmod(cents, 100)
    text = f"{whole:,}".replace(",", ".")
    return f"{sign}R$ {text}" + (f",{frac:02d}" if frac else "")
