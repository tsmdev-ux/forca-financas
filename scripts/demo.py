"""Sobe o app com dados fictícios, sem Telegram e sem IA.

Uso: python scripts/demo.py    →  http://127.0.0.1:8000  (senha: demo)
FORCA_DEMO_TODAY=2026-11-18 fixa a data; os dados ficam em demo-data/ e são recriados a cada execução.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "demo-data"
shutil.rmtree(DATA, ignore_errors=True)
os.environ["FORCA_DATA_DIR"] = str(DATA)
for name in ("TELEGRAM_BOT_TOKEN", "DEEPSEEK_API_KEY"):
    os.environ.pop(name, None)
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from forca import config, db, finance, ledger, ops  # noqa: E402

TODAY = date.fromisoformat(os.environ["FORCA_DEMO_TODAY"]) if "FORCA_DEMO_TODAY" in os.environ else config.today()
config.today = lambda: TODAY
config.now = lambda: datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=config.TZ)
config.PASSWORD = "demo"


def day_in(month_offset: int, day: int) -> date:
    return finance.day_in_month(finance.add_months(finance.month_of(TODAY), month_offset), day)


# Gastos do mês atual e dos dois anteriores: (descrição, valor em centavos, dia)
SPENDING = [
    ("Mercado", 31240, 3),
    ("Padaria", 1850, 4),
    ("iFood", 5890, 5),
    ("Uber", 2350, 6),
    ("Farmácia", 6790, 7),
    ("Cinema", 6400, 8),
    ("Mercado", 14800, 9),
    ("Almoço", 4200, 10),
    ("Gasolina", 18000, 12),
    ("iFood", 7200, 13),
    ("Diarista", 18000, 14),
    ("Ração", 9500, 15),
    ("Barbearia", 5500, 16),
    ("Mercado", 22600, 17),
    ("Almoço", 3900, 18),
    ("Uber", 1800, 20),
    ("Livro", 4900, 21),
    ("iFood", 6400, 23),
    ("Mercado", 18700, 25),
]


def seed() -> None:
    db.init()
    with db.tx() as c:
        db.set_setting(c, "started_month", finance.month_of(day_in(-2, 1)))
        db.set_setting(c, "started_date", day_in(-2, 1).isoformat())
        ops.add_recurring(c, "income", "Salário", 620000, 5)
        for name, amount, day in [
            ("Aluguel", 165000, 10),
            ("Luz", 18000, 15),
            ("Internet", 11000, 18),
            ("Academia", 9000, 12),
        ]:
            ops.add_recurring(c, "expense", name, amount, day)

        card = c.execute(
            "SELECT * FROM cards WHERE id = ?", (ops.add_card(c, "Cartão Roxo", 3, 10, 800000),)
        ).fetchone()
        ledger.add_expense(c, 89900, "Fone de ouvido", day_in(-1, 20), installments=3, card=card)

        ops.add_debt(c, "Rotativo do cartão", 240000, 14, 48000, 22)
        ops.add_debt(c, "Empréstimo pessoal", 650000, 3.9, 41000, 15)
        ops.set_debt_plan(c, 20000, "avalanche")

        for month, scale in ((-2, 0.6), (-1, 0.75), (0, 0.65)):
            for description, amount, day in SPENDING:
                when = day_in(month, day)
                if when < TODAY:
                    ledger.add_expense(c, int(amount * scale), description, when, link=False)

        # O que venceu até hoje já foi pago: a demo mostra um mês em dia.
        for item in finance.upcoming(c, TODAY, 0):
            if item["days"] < 0:
                ledger.mark_paid(c, item["type"], item["id"], item["month"], date.fromisoformat(item["due"]))

        ops.set_category_budget(c, "mercado", 70000)
        ops.set_category_budget(c, "comida", 30000)
        ops.set_category_budget(c, "transporte", 30000)
        ops.add_category(c, "Pilates", "dumbbell")

        reserve = ops.add_goal(c, "Reserva de emergência", 300000, None, 15000)
        ops.deposit_goal(c, reserve, 45000, TODAY - timedelta(days=9))
        ops.add_goal(c, "Viagem de férias", 450000, finance.add_months(finance.month_of(TODAY), 12))
        ledger.create_pause(c, "Tênis de corrida", 49900)


if __name__ == "__main__":
    seed()
    from forca.web import app

    print("Demo em http://127.0.0.1:8000  (senha: demo)")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning")
