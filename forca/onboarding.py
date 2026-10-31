"""Cadastro por conversa: uma pergunta por vez, com botões quando dá.
Cada resposta entra aqui como texto; o estado fica no banco e sobrevive a reinícios."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from . import db, ledger, ops, parser
from .finance import brl

KEY = "onboarding"
SKIP, YES, NO, DONE, UNKNOWN, CONFIRM, FIX = "pular", "sim", "nao", "terminei", "nao sei", "confirmar", "corrigir"
DAYS = ["1", "5", "10", "15", "20", "25"]
BILLS = ["Aluguel", "Luz", "Água", "Internet", "Celular", "Condomínio"]
CARDS = ["Nubank", "Itaú", "Bradesco", "Santander", "Inter", "C6"]


@dataclass
class Reply:
    text: str
    options: list[tuple[str, str]] = field(default_factory=list)  # (rótulo, valor)
    finished: bool = False


def active(c: sqlite3.Connection) -> bool:
    return db.get_setting(c, KEY) not in (None, "")


def cancel(c: sqlite3.Connection) -> None:
    db.set_setting(c, KEY, "")


def _save(c: sqlite3.Connection, state: dict) -> None:
    db.set_setting(c, KEY, json.dumps(state, ensure_ascii=False))


def money(text: str) -> int | None:
    """Só aceita resposta que é um valor: "mercado 50" aqui é engano, não renda."""
    norm = parser.normalize(text).strip(" .!")
    match = re.fullmatch(
        r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(\s*(?:k|mil))?(?:\s*(?:reais|real|por mes|ao mes))?",
        norm,
    )
    if not match:
        return None
    cents = parser.to_cents(match[1], match[2])
    return cents if cents > 0 else None


def _day(text: str) -> int | None:
    match = re.fullmatch(r"(?:dia\s*)?(\d{1,2})", parser.normalize(text).strip(" .!"))
    return int(match[1]) if match and 1 <= int(match[1]) <= 31 else None


def _rate(text: str) -> float | None:
    match = re.fullmatch(
        r"(\d{1,3}(?:[.,]\d{1,2})?)\s*%?(?:\s*(?:ao|por|a)\s*mes)?", parser.normalize(text).strip(" .!")
    )
    if not match:
        return None
    value = float(match[1].replace(",", "."))
    return value if value <= 100 else None


def _day_options() -> list[tuple[str, str]]:
    return [(d, d) for d in DAYS]


def start(c: sqlite3.Connection, today: date) -> Reply:
    ledger.ensure_started(c, today)
    if c.execute("SELECT 1 FROM recurring WHERE kind = 'income' AND active = 1").fetchone():
        state = {"step": "bill_name", "data": {}}
        _save(c, state)
        return _ask_bill(
            c,
            "Sua renda já está aqui, então vamos às contas fixas. Responda uma coisa por vez; pode mudar tudo depois.\n\n",
        )
    _save(c, {"step": "income_amount", "data": {}})
    return Reply(
        "Vamos cadastrar o básico, uma pergunta por vez. Valores aproximados servem.\n\n<b>Quanto você ganha por mês?</b>\nEx.: 4000"
    )


def _ask_bill(c: sqlite3.Connection, prefix: str = "") -> Reply:
    existing = {
        parser.normalize(r["name"])
        for r in c.execute("SELECT name FROM recurring WHERE active = 1 AND kind = 'expense'")
    }
    options = [(b, b) for b in BILLS if parser.normalize(b) not in existing]
    return Reply(
        f"{prefix}<b>Qual conta você paga todo mês?</b>\nToque em uma ou escreva o nome.",
        [*options, ("Terminei", DONE)],
    )


def _ask_card(prefix: str = "", another: bool = False) -> Reply:
    question = "Tem outro cartão de crédito?" if another else "Você usa cartão de crédito?"
    return Reply(f"{prefix}<b>{question}</b>", [("Sim", YES), ("Não", NO)])


def _ask_debt(prefix: str = "", another: bool = False) -> Reply:
    question = "Tem mais alguma dívida?" if another else "Você tem alguma dívida ou empréstimo?"
    return Reply(f"{prefix}<b>{question}</b>", [("Sim", YES), ("Não", NO)])


_NOT_MONEY = "Não entendi o valor. Mande só o número, como 1200."
_NOT_DAY = "Não entendi o dia. Mande um número de 1 a 31."


def _money_step(c: sqlite3.Connection, state: dict, text: str, key: str) -> tuple[int | None, Reply | None]:
    """Valor fora da realidade pede confirmação antes de seguir."""
    data = state["data"]
    if state.get("confirm") is not None:
        cents = state.pop("confirm")
        if text == CONFIRM:
            data[key] = cents
            return cents, None
        _save(c, state)
        return None, Reply("Certo. Qual é o valor?")
    cents = money(text)
    if cents is None:
        return None, Reply(_NOT_MONEY)
    if ops.looks_too_big(c, cents):
        state["confirm"] = cents
        _save(c, state)
        return None, Reply(
            f"Só para conferir: <b>{brl(cents)}</b>. É isso mesmo?", [("Sim", CONFIRM), ("Corrigir", FIX)]
        )
    data[key] = cents
    return cents, None


def answer(c: sqlite3.Connection, text: str, today: date) -> Reply:
    state = json.loads(db.get_setting(c, KEY))
    text = text.strip()
    low = parser.normalize(text)
    step, data = state["step"], state["data"]

    def go(next_step: str, reply: Reply) -> Reply:
        state["step"] = next_step
        _save(c, state)
        return reply

    if step == "income_amount":
        parsed = parser.parse(text, today)
        if parsed and parsed.kind == "recurring_income":
            ops.add_recurring(c, "income", parsed.description, parsed.amount_cents, parsed.installments)
            return go(
                "bill_name", _ask_bill(c, f"Anotado: {brl(parsed.amount_cents)} todo dia {parsed.installments}.\n\n")
            )
        cents, stop = _money_step(c, state, text, "income")
        if stop:
            return stop
        return go("income_day", Reply("<b>Em que dia esse dinheiro cai?</b>", _day_options()))

    if step == "income_day":
        day = _day(text)
        if day is None:
            return Reply(_NOT_DAY, _day_options())
        ops.add_recurring(c, "income", "Salário", data["income"], day)
        return go(
            "bill_name", _ask_bill(c, f"Anotado: {brl(data['income'])} todo dia {day}.\n\nAgora as contas fixas.\n")
        )

    if step == "bill_name":
        if low == DONE:
            return go("card_ask", _ask_card())
        parsed = parser.parse(text, today)
        if parsed and parsed.kind == "recurring_expense":
            ops.add_recurring(c, "expense", parsed.description, parsed.amount_cents, parsed.installments)
            return _ask_bill(
                c, f"Anotado: {parsed.description}, {brl(parsed.amount_cents)} todo dia {parsed.installments}.\n\n"
            )
        data["bill"] = text[:80]
        return go("bill_amount", Reply(f"<b>Quanto é {_e(text)}, mais ou menos?</b>"))

    if step == "bill_amount":
        cents, stop = _money_step(c, state, text, "bill_amount")
        if stop:
            return stop
        return go("bill_day", Reply("<b>Vence em que dia?</b>", _day_options()))

    if step == "bill_day":
        day = _day(text)
        if day is None:
            return Reply(_NOT_DAY, _day_options())
        ops.add_recurring(c, "expense", data["bill"], data["bill_amount"], day)
        return go(
            "bill_name", _ask_bill(c, f"Anotado: {_e(data['bill'])}, {brl(data['bill_amount'])} todo dia {day}.\n\n")
        )

    if step == "card_ask":
        if low in (YES, "s"):
            return go("card_name", Reply("<b>Qual cartão?</b>", [(n, n) for n in CARDS]))
        if low in (NO, "n"):
            return go("debt_ask", _ask_debt())
        return _ask_card()

    if step == "card_name":
        data["card"] = text[:80]
        return go(
            "card_closing",
            Reply(
                "<b>Em que dia a fatura fecha?</b>\nFica no app do banco. Se não souber, costuma ser uns 7 dias antes do vencimento."
            ),
        )

    if step == "card_closing":
        day = _day(text)
        if day is None:
            return Reply(_NOT_DAY)
        data["closing"] = day
        return go("card_due", Reply("<b>Em que dia ela vence?</b>", _day_options()))

    if step == "card_due":
        day = _day(text)
        if day is None:
            return Reply(_NOT_DAY, _day_options())
        data["due"] = day
        return go("card_invoice", Reply("<b>Quanto a fatura atual já tem?</b>", [("Não sei agora", SKIP)]))

    if step == "card_invoice":
        cents = None
        if low != SKIP and "nao sei" not in low:
            cents, stop = _money_step(c, state, text, "invoice")
            if stop:
                return stop
        card_id = ops.add_card(c, data["card"], data["closing"], data["due"])
        if cents:
            ledger.set_opening_invoice(c, card_id, cents, today)
        return go("card_ask", _ask_card(f"Anotado: {_e(data['card'])}.\n\n", another=True))

    if step == "debt_ask":
        if low in (YES, "s"):
            return go("debt_name", Reply("<b>De quem é essa dívida?</b>\nEx.: Rotativo Nubank, empréstimo do banco."))
        if low in (NO, "n"):
            return _finish(c, today)
        return _ask_debt()

    if step == "debt_name":
        data["debt"] = text[:80]
        return go("debt_balance", Reply("<b>Quanto você deve, mais ou menos?</b>"))

    if step == "debt_balance":
        cents, stop = _money_step(c, state, text, "balance")
        if stop:
            return stop
        return go(
            "debt_rate",
            Reply(
                "<b>Quantos % de juros ao mês?</b>\nEx.: 14. Rotativo de cartão costuma passar de 10%.",
                [("Não sei", UNKNOWN)],
            ),
        )

    if step == "debt_rate":
        if low == UNKNOWN or "nao sei" in low:
            data["rate"] = 0
        else:
            rate = _rate(text)
            if rate is None:
                return Reply("Não entendi. Mande só o número, como 14.", [("Não sei", UNKNOWN)])
            data["rate"] = rate
        return go("debt_min", Reply("<b>Quanto você paga por mês nela?</b>\nA parcela ou o mínimo."))

    if step == "debt_min":
        cents, stop = _money_step(c, state, text, "minimum")
        if stop:
            return stop
        return go("debt_day", Reply("<b>Vence em que dia?</b>", _day_options()))

    if step == "debt_day":
        day = _day(text)
        if day is None:
            return Reply(_NOT_DAY, _day_options())
        data["debt_due"] = day
        return go("debt_late", Reply("<b>Ela está em atraso?</b>", [("Sim", YES), ("Não", NO)]))

    if step == "debt_late":
        if low not in (YES, NO, "s", "n"):
            return Reply("Está em atraso?", [("Sim", YES), ("Não", NO)])
        ops.add_debt(
            c, data["debt"], data["balance"], data["rate"], data["minimum"], data["debt_due"], low in (YES, "s")
        )
        note = (
            "Sem a taxa de juros, a previsão de quitação fica otimista. Quando souber, me diga.\n\n"
            if not data["rate"]
            else ""
        )
        return go("debt_ask", _ask_debt(f"Anotado: {_e(data['debt'])}.\n{note}\n", another=True))

    cancel(c)
    return _finish(c, today)


def _finish(c: sqlite3.Connection, today: date) -> Reply:
    cancel(c)
    return Reply(
        "<b>Pronto, o básico está cadastrado.</b> A partir de agora, é só mandar cada gasto: <code>mercado 87</code>.",
        finished=True,
    )


def _e(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
