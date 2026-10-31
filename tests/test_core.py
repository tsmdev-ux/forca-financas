from datetime import date

import pytest

from forca import finance, importers, ledger, parser

TODAY = date(2026, 11, 11)  # quarta-feira; novembro tem 30 dias


# ---------- parser ----------


@pytest.mark.parametrize(
    "text,cents,desc",
    [
        ("mercado 87,50", 8750, "Mercado"),
        ("87 mercado", 8700, "Mercado"),
        ("gastei 40 no ifood", 4000, "Ifood"),
        ("r$ 1.200 aluguel", 120000, "Aluguel"),
        ("uber 23.5", 2350, "Uber"),
        ("almoço 32", 3200, "Almoço"),
        ("farmácia 45,90", 4590, "Farmácia"),
        ("notebook 2k", 200000, "Notebook"),
        ("sapato 50 reais", 5000, "Sapato"),
    ],
)
def test_parse_expense(text, cents, desc):
    p = parser.parse(text, TODAY)
    assert p and p.kind == "expense" and p.amount_cents == cents and p.description == desc


def test_parse_transcribed_audio():
    p = parser.parse("O Uber 25 R$.", TODAY)
    assert (p.amount_cents, p.description, p.category) == (2500, "Uber", "transporte")
    assert parser.parse("Mercado 87.", TODAY).description == "Mercado"


def test_parse_dates():
    assert parser.parse("uber 20 ontem", TODAY).date == date(2026, 11, 10)
    assert parser.parse("uber 20 anteontem", TODAY).date == date(2026, 11, 9)
    assert parser.parse("uber 20 dia 5", TODAY).date == date(2026, 11, 5)
    assert parser.parse("uber 20 dia 28", TODAY).date == date(2026, 10, 28)  # futuro vira mês passado
    assert parser.parse("uber 20 03/11", TODAY).date == date(2026, 11, 3)


def test_parse_installments_and_card():
    p = parser.parse("tv 1200 em 10x no nubank", TODAY, ("Nubank", "Inter"))
    assert (p.amount_cents, p.installments, p.card_hint, p.description) == (120000, 10, "Nubank", "Tv")
    assert parser.parse("tenis 300 no cartão", TODAY).card_hint == "*"


def test_parse_income_and_zero():
    p = parser.parse("recebi 3000 freela", TODAY)
    assert p.kind == "income" and p.amount_cents == 300000
    assert parser.parse("salário 4.200,00", TODAY).kind == "income"
    for text in ("nada hoje", "0", "não gastei nada", "hoje foi zero"):
        assert parser.parse(text, TODAY).kind == "zero_day", text


@pytest.mark.parametrize(
    "text",
    [
        "quanto gastei esse mês?",
        "posso comprar um tênis de 400?",
        "2 pizzas 80",
        "oi",
        "como saio das dívidas",
        "mercado",
    ],
)
def test_parse_hands_off_to_agent(text):
    assert parser.parse(text, TODAY) is None


@pytest.mark.parametrize(
    "text",
    [
        "exclui essa conta de 4000",
        "apaga o gasto de 50",
        "corrige o aluguel para 1200",
        "isso foi 300",
        "remove a conta 4000",
        "tira 50 do mercado",
        "muda o salário para 5000",
    ],
)
def test_commands_are_never_logged_as_expense(text):
    assert parser.parse(text, TODAY) is None


def test_ganhou_is_income():
    p = parser.parse("ganhou 4000 todo dia 5", TODAY)
    assert p.kind == "recurring_income" and p.description == "Salário" and p.amount_cents == 400000
    assert parser.parse("ganhei 300 freela", TODAY).kind == "income"
    assert parser.parse("ganhou 300", TODAY).kind == "income"


def test_huge_amount_needs_confirmation(c):
    from forca import ops

    assert ops.capture(c, "ganhou 4.000.000 todo dia 5", TODAY, "t")["type"] == "check"
    assert c.execute("SELECT COUNT(*) FROM recurring").fetchone()[0] == 0
    assert ops.capture(c, "ganhou 4.000.000 todo dia 5", TODAY, "t", confirmed=True)["type"] == "recurring"
    assert ops.capture(c, "mercado 87", TODAY, "t")["type"] == "expense"


def test_purchase_question():
    assert parser.parse_purchase_question("posso comprar um tênis de 400?") == ("Tênis", 40000, 1)
    assert parser.parse_purchase_question("quero comprar uma tv por 2000 em 10x")[1:] == (200000, 10)
    assert parser.parse_purchase_question("quanto gastei?") is None


def test_categories():
    assert parser.guess_category("iFood") == "comida"
    assert parser.guess_category("Mercado Livre") == "compras"
    assert parser.guess_category("Mercado") == "mercado"
    assert parser.guess_category("xyz") == "outros"
    assert parser.guess_category("Loja X", {"loja": "compras"}) == "compras"


# ---------- fatura ----------


def test_invoice_month():
    # fecha dia 3, vence dia 10: compra dia 2 pega a fatura deste mês; dia 3 em diante, a próxima
    assert finance.invoice_month_for(date(2026, 11, 2), 3, 10) == "2026-11"
    assert finance.invoice_month_for(date(2026, 11, 3), 3, 10) == "2026-12"
    # fecha dia 25, vence dia 5 do mês seguinte
    assert finance.invoice_month_for(date(2026, 11, 20), 25, 5) == "2026-12"
    assert finance.invoice_month_for(date(2026, 11, 26), 25, 5) == "2027-01"
    # virada de ano e fim de mês curto
    assert finance.invoice_month_for(date(2026, 12, 20), 10, 17) == "2027-01"
    assert finance.invoice_month_for(date(2027, 2, 28), 31, 8) == "2027-04"


def _setup(c):
    c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('income', 'Salário', 500000, 5)")
    c.execute(
        "INSERT INTO recurring (kind, name, amount_cents, day, category) VALUES ('expense', 'Aluguel', 150000, 10, 'moradia')"
    )
    c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('expense', 'Internet', 10000, 15)")


# ---------- número do dia ----------


def test_daily_number(c):
    _setup(c)
    # sobra 340.000 em novembro; no dia 11 restam 20 dias contando hoje
    t = finance.today_status(c, TODAY)
    assert t.budget.available == 340000 and t.days_left == 20
    assert t.daily_allowance == 17000 and t.left_today == 17000 and t.status == "ok"

    ledger.add_expense(c, 5000, "Mercado", TODAY)
    t = finance.today_status(c, TODAY)
    # o limite de hoje não muda quando se gasta; o que resta muda
    assert t.daily_allowance == 17000 and t.left_today == 12000 and t.spent_today == 5000
    assert t.tomorrow == (340000 - 5000) // 19

    ledger.add_expense(c, 30000, "Sapato", date(2026, 11, 9))
    t = finance.today_status(c, TODAY)
    assert t.daily_allowance == (340000 - 30000) // 20


def test_bill_is_not_counted_twice(c):
    _setup(c)
    before = finance.today_status(c, TODAY).budget.available
    r = ledger.add_expense(c, 150000, "aluguel", TODAY)
    assert r["linked"] == "bill"
    t = finance.today_status(c, TODAY)
    assert t.budget.available == before and t.spent_today == 0
    # conta paga mais cara muda a sobra
    r = ledger.add_expense(c, 12000, "internet", TODAY)
    assert r["linked"] == "bill"
    assert finance.today_status(c, TODAY).budget.available == before - 2000


def test_income_reconciles(c):
    _setup(c)
    assert ledger.add_income(c, 510000, "Recebi", TODAY)["linked"] == "income"
    assert finance.month_budget(c, "2026-11").income == 510000
    ledger.add_income(c, 30000, "Freela", TODAY)
    assert finance.month_budget(c, "2026-11").income == 540000


def test_installments_commit_future_months(c):
    _setup(c)
    c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 3, 10)")
    card = c.execute("SELECT * FROM cards").fetchone()
    r = ledger.add_expense(c, 100000, "TV", TODAY, installments=3, card=card)
    assert len(r["ids"]) == 3
    rows = c.execute("SELECT * FROM transactions ORDER BY id").fetchall()
    assert [x["amount_cents"] for x in rows] == [33334, 33333, 33333]
    assert sum(x["amount_cents"] for x in rows) == 100000
    assert [x["invoice_month"] for x in rows] == ["2026-12", "2027-01", "2027-02"]
    assert [x["committed"] for x in rows] == [0, 1, 1]

    nov, dec = finance.month_budget(c, "2026-11"), finance.month_budget(c, "2026-12")
    assert nov.spent == 33334 and nov.committed == 0
    assert dec.spent == 0 and dec.committed == 33333  # pesa como compromisso, reduz a sobra de dezembro
    assert finance.invoice_total(c, 1, "2026-12") == 33334

    removed = ledger.delete_transaction(c, r["ids"][0])  # desfazer apaga a compra inteira
    assert len(removed) == 3 and finance.month_budget(c, "2026-12").committed == 0


def test_opening_invoice_weighs_on_due_month(c):
    _setup(c)
    c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 20, 28)")
    ledger.set_opening_invoice(c, 1, 80000, TODAY)
    b = finance.month_budget(c, "2026-11")
    assert b.committed == 80000 and b.available == 260000
    # registrar de novo substitui, não soma
    ledger.set_opening_invoice(c, 1, 90000, TODAY)
    assert finance.month_budget(c, "2026-11").committed == 90000


def test_deficit_rolls_but_surplus_does_not(c):
    _setup(c)
    ledger.ensure_started(c, date(2026, 10, 1))
    ledger.add_expense(c, 400000, "Viagem", date(2026, 10, 20))  # 60.000 acima da sobra de 340.000
    b = finance.month_budget(c, "2026-11")
    assert b.carry == 60000 and b.available == 280000
    assert finance.month_budget(c, "2026-12").carry == 0  # novembro não estourou, dívida com o mês acabou


def test_broken_month_states(c):
    c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('income', 'Salário', 100000, 5)")
    c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('expense', 'Aluguel', 150000, 20)")
    t = finance.today_status(c, TODAY)
    assert t.status == "broken" and t.daily_allowance == 0
    assert finance.focus(c, TODAY)["title"] == "O mês não fecha ainda"


def test_setup_state(c):
    assert finance.today_status(c, TODAY).status == "setup"


# ---------- dívidas ----------


def _debt(name, bal, rate, minimum):
    return {"name": name, "balance_cents": bal, "monthly_rate": rate, "min_payment_cents": minimum}


def test_simulation_hand_checked():
    # 1000,00 a 10% ao mês pagando 600,00: 1100-600=500; 550-550=0
    plan = finance.simulate_debts([_debt("a", 100000, 10, 60000)], 0)
    assert plan["months"] == 2 and plan["total_interest_cents"] == 15000 and plan["timeline"] == [100000, 50000, 0]


def test_minimum_below_interest_never_ends():
    plan = finance.simulate_debts([_debt("rotativo", 500000, 14, 30000)], 0)
    assert plan["feasible"] is False and plan["months"] is None


def test_expensive_debt_falling_while_cheap_grows_is_not_called_endless():
    # no começo o total sobe, mas o extra derruba a cara e o plano termina
    debts = [_debt("cara", 100000, 15, 0), _debt("barata", 900000, 2, 0)]
    plan = finance.simulate_debts(debts, 24000, "avalanche")
    assert plan["feasible"] is True and plan["timeline"][1] > plan["timeline"][0]


def test_avalanche_beats_snowball_on_interest():
    debts = [_debt("cartao", 300000, 12, 20000), _debt("emprestimo", 100000, 2, 10000)]
    a = finance.simulate_debts(debts, 30000, "avalanche")
    s = finance.simulate_debts(debts, 30000, "snowball")
    assert a["total_interest_cents"] < s["total_interest_cents"]
    assert s["payoff_order"][0]["name"] == "emprestimo"


def test_freed_payment_rolls_to_next_debt():
    debts = [_debt("a", 10000, 0, 10000), _debt("b", 100000, 0, 10000)]
    # mês 1: paga a(10k) + b(10k); depois os 20k inteiros vão para b
    assert finance.simulate_debts(debts, 0)["months"] == 6


def test_debt_payment_lowers_balance_and_undo_restores(c):
    c.execute(
        "INSERT INTO debts (id, name, balance_cents, monthly_rate, min_payment_cents) VALUES (1, 'Empréstimo Itaú', 100000, 3, 20000)"
    )
    r = ledger.add_expense(c, 20000, "parcela empréstimo itaú", TODAY)
    assert r["linked"] == "debt"
    assert c.execute("SELECT balance_cents FROM debts").fetchone()[0] == 80000
    assert finance.month_budget(c, "2026-11").spent == 0
    ledger.delete_transaction(c, r["ids"][0])
    assert c.execute("SELECT balance_cents FROM debts").fetchone()[0] == 100000


def test_debt_budget_uses_plan_or_paid(c):
    c.execute(
        "INSERT INTO debts (id, name, balance_cents, monthly_rate, min_payment_cents) VALUES (1, 'X', 100000, 3, 20000)"
    )
    assert finance.month_budget(c, "2026-11").debts == 20000
    ledger.mark_paid(c, "debt", 1, "2026-11", TODAY, 50000)
    assert finance.month_budget(c, "2026-11").debts == 50000


# ---------- vencimentos ----------


def test_upcoming_and_overdue(c):
    _setup(c)
    ledger.ensure_started(c, date(2026, 11, 1))
    items = finance.upcoming(c, TODAY, 7)
    by_name = {i["name"]: i for i in items}
    assert by_name["Aluguel"]["days"] == -1  # venceu ontem
    assert by_name["Internet"]["days"] == 4
    ledger.mark_paid(c, "bill", by_name["Aluguel"]["id"], "2026-11", TODAY)
    assert "Aluguel" not in {i["name"] for i in finance.upcoming(c, TODAY, 7)}


def test_upcoming_ignores_months_before_start(c):
    _setup(c)
    ledger.ensure_started(c, date(2026, 11, 1))
    names = [(i["name"], i["month"]) for i in finance.upcoming(c, date(2026, 11, 2), 3)]
    assert ("Aluguel", "2026-10") not in names  # não cobra o que é de antes do app existir


def test_invoice_in_upcoming_until_paid(c):
    c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 3, 15)")
    card = c.execute("SELECT * FROM cards").fetchone()
    ledger.ensure_started(c, date(2026, 11, 1))
    ledger.add_expense(c, 5000, "Loja", date(2026, 11, 1), card=card)
    item = next(i for i in finance.upcoming(c, TODAY, 7) if i["type"] == "invoice")
    assert item["amount_cents"] == 5000 and item["days"] == 4
    ledger.mark_paid(c, "invoice", 1, "2026-11", TODAY)
    assert not [i for i in finance.upcoming(c, TODAY, 7) if i["type"] == "invoice"]


# ---------- freio ----------


def test_assess_purchase(c):
    _setup(c)
    assert finance.assess_purchase(c, TODAY, 5000)["verdict"] == "yes"  # limite 170
    assert finance.assess_purchase(c, TODAY, 60000)["verdict"] == "wait"  # > 2 dias de limite
    assert finance.assess_purchase(c, TODAY, 400000)["verdict"] == "no"  # estoura o mês
    a = finance.assess_purchase(c, TODAY, 60000, 3)
    assert a["first_payment_cents"] == 20000 and a["future_months_committed"] == 2


def test_pause_flow(c):
    _setup(c)
    pid = ledger.create_pause(c, "Tênis", 40000)
    ledger.resolve_pause(c, pid, "skipped", TODAY)
    assert finance.saved_by_pauses(c) == 40000
    assert ledger.resolve_pause(c, pid, "bought", TODAY) is None  # já resolvida
    assert finance.month_budget(c, "2026-11").spent == 0


def test_streak(c):
    ledger.add_expense(c, 100, "a", date(2026, 11, 8))
    ledger.zero_day(c, date(2026, 11, 9))
    ledger.add_expense(c, 100, "b", date(2026, 11, 10))
    assert finance.streak(c, TODAY) == 3  # hoje ainda não registrado não quebra
    ledger.add_expense(c, 100, "c", TODAY)
    assert finance.streak(c, TODAY) == 4
    assert finance.streak(c, date(2026, 11, 13)) == 0


def test_risky_weekday(c):
    for d in (date(2026, 11, 4), date(2026, 10, 28), date(2026, 10, 21), date(2026, 10, 14)):  # quartas
        ledger.add_expense(c, 8000, "ifood", d)
    ledger.add_expense(c, 2000, "ifood", date(2026, 11, 2))
    r = finance.risky_weekday(c, TODAY)
    assert r["category"] == "comida" and r["occurrences"] == 4
    assert finance.risky_weekday(c, date(2026, 11, 12)) is None


# ---------- importação ----------

NUBANK_FATURA = b"""date,title,amount
2026-11-02,Padaria Central,23.50
2026-11-03,Netflix,55.90
2026-11-05,Loja Tal - Parcela 2/3,100.00
2026-11-06,Pagamento recebido,-500.00
2026-11-07,Estorno Loja,-10.00
"""

ITAU_CSV = """Extrato conta corrente
Agência;Conta
data;lançamento;valor
05/11/2026;SALARIO EMPRESA;5.000,00
06/11/2026;PIX MERCADO BOM;-87,50
07/11/2026;PAGAMENTO FATURA CARTAO;-900,00
""".encode("cp1252")

OFX = b"""OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261106120000[-3:BRT]<TRNAMT>-87.50<MEMO>COMPRA MERCADO</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261105<TRNAMT>1000.00<MEMO>PIX RECEBIDO</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


def test_csv_bank_statement(c):
    items, is_card = importers.parse_file("extrato.csv", ITAU_CSV)
    assert is_card is False
    amounts = {i.description: i.amount_cents for i in items}
    assert amounts["PIX MERCADO BOM"] == 8750 and amounts["SALARIO EMPRESA"] == -500000
    s = importers.import_items(c, items, None, TODAY)
    assert s["added"] == 2 and s["ignored"] == 1  # pagamento de fatura não é gasto
    assert finance.month_budget(c, "2026-11").spent == 8750


def test_csv_invoice_nubank(c):
    c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 28, 5)")
    card = c.execute("SELECT * FROM cards").fetchone()
    items, is_card = importers.parse_file("nubank.csv", NUBANK_FATURA)
    assert is_card is True
    s = importers.import_items(c, items, card, TODAY)
    assert s["ignored"] == 1
    # parcela 2/3 projeta a 3/3 na próxima fatura
    rows = c.execute("SELECT * FROM transactions WHERE installment_no IS NOT NULL ORDER BY installment_no").fetchall()
    assert [(r["installment_no"], r["committed"], r["invoice_month"]) for r in rows] == [
        (2, 1, "2026-12"),
        (3, 1, "2027-01"),
    ]
    # o estorno abate da fatura
    assert finance.invoice_total(c, 1, "2026-12") == 2350 + 5590 + 10000 - 1000


def test_next_invoice_does_not_duplicate_installment(c):
    c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 28, 5)")
    card = c.execute("SELECT * FROM cards").fetchone()
    importers.import_items(
        c,
        importers.parse_file(
            "a.csv", b"date,title,amount\n2026-11-05,Loja Tal - Parcela 2/3,100.00\n2026-11-06,Outra,1.00\n"
        )[0],
        card,
        TODAY,
    )
    importers.import_items(
        c,
        importers.parse_file(
            "b.csv", b"date,title,amount\n2026-12-05,Loja Tal - Parcela 3/3,100.00\n2026-12-06,Mais,1.00\n"
        )[0],
        card,
        TODAY,
    )
    assert c.execute("SELECT COUNT(*) FROM transactions WHERE installment_no = 3").fetchone()[0] == 1


def test_ofx(c):
    items, is_card = importers.parse_file("x.ofx", OFX)
    assert not is_card and [(i.amount_cents, i.day.day) for i in items] == [(8750, 6), (-100000, 5)]


def test_reimport_is_idempotent(c):
    items, _ = importers.parse_file("x.ofx", OFX)
    assert importers.import_items(c, items, None, TODAY)["added"] == 2
    s = importers.import_items(c, items, None, TODAY)
    assert s["added"] == 0 and s["already"] == 2


def test_import_matches_manual_entry(c):
    ledger.add_expense(c, 8750, "mercado", date(2026, 11, 5), source="telegram")
    items, _ = importers.parse_file("x.ofx", OFX)
    s = importers.import_items(c, items, None, TODAY)
    assert s["matched"] == 1 and s["added"] == 1
    assert c.execute("SELECT COUNT(*) FROM transactions WHERE kind='expense'").fetchone()[0] == 1
    # o mesmo arquivo de novo continua não duplicando
    assert importers.import_items(c, items, None, TODAY)["already"] == 2


def test_same_day_same_value_are_distinct(c):
    csv = b"data;descricao;valor\n05/11/2026;CAFE;-5,00\n05/11/2026;CAFE;-5,00\n"
    s = importers.import_items(c, importers.parse_file("x.csv", csv)[0], None, TODAY)
    assert s["added"] == 2


def test_undo_batch(c):
    items, _ = importers.parse_file("x.ofx", OFX)
    s = importers.import_items(c, items, None, TODAY)
    assert importers.undo_batch(c, s["batch_id"]) == 2
    assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_import_rejects_garbage(c):
    with pytest.raises(importers.ImportFailed):
        importers.parse_file("x.csv", b"a,b,c\n1,2,3\n")
    with pytest.raises(importers.ImportFailed):
        importers.parse_file("x.xlsx", b"PK....")


def test_brl():
    assert finance.brl(123456) == "R$ 1.234,56"
    assert finance.brl(5000) == "R$ 50"
    assert finance.brl(-5) == "−R$ 0,05"


# ---------- categorias ----------

ICON_NAMES = {
    "cart",
    "plate",
    "car",
    "home",
    "tool",
    "bulb",
    "repeat",
    "health",
    "ticket",
    "plane",
    "bag",
    "shirt",
    "scissors",
    "book",
    "people",
    "paw",
    "gift",
    "receipt",
    "dot",
    "card",
    "coin",
}


def test_new_categories_guess():
    assert parser.guess_category("Ração") == "pets"
    assert parser.guess_category("Barbearia") == "beleza"
    assert parser.guess_category("Tênis") == "roupas"
    assert parser.guess_category("Hotel") == "viagem"
    assert parser.guess_category("IPVA") == "impostos"


def test_requested_categories(c):
    labels = {r["key"]: r["label"] for r in finance.category_list(c)}
    assert labels["lazer"] == "Lazer" and labels["comida"] == "Alimentação" and labels["servicos"] == "Serviços"
    assert parser.guess_category("Diarista") == "servicos" and parser.guess_category("Almoço") == "comida"


def test_custom_category_life_cycle(c):
    from forca import ops

    key = ops.add_category(c, "Pilates", "🧘")
    assert key == "pilates" and any(r["key"] == "pilates" for r in finance.category_list(c))
    r = ops.capture(c, "pilates 90", TODAY, "t")
    assert r["category"] == "pilates"
    ops.set_category_budget(c, "pilates", 20000)
    row = next(x for x in finance.categories_for(c, "2026-11") if x["category"] == "pilates")
    assert row["label"] == "Pilates" and row["icon"] == "🧘" and row["limit_cents"] == 20000
    assert {r["icon"] for r in finance.category_list(c) if r["builtin"]} <= set(ICON_NAMES)
    with pytest.raises(ops.Invalid):
        ops.add_category(c, "pilates")
    with pytest.raises(ops.Invalid):
        ops.remove_category(c, "outros")
    assert ops.remove_category(c, "pilates") == 1
    assert c.execute("SELECT category FROM transactions").fetchone()[0] == "outros"
    assert not c.execute("SELECT 1 FROM category_budgets").fetchone()
    assert ops.capture(c, "pilates 40", TODAY, "t")["category"] == "outros"
    assert ops.add_category(c, "Pilates") == "pilates"  # dá para recriar


def test_unknown_category_is_rejected(c):
    from forca import ops

    with pytest.raises(ops.Invalid):
        ops.set_category_budget(c, "inventada", 100)


# ---------- metas ----------


def test_goal_plan_reserves_budget_and_deposit_is_not_expense(c):
    from forca import ops

    _setup(c)
    before = finance.month_budget(c, "2026-11").available
    gid = ops.add_goal(c, "Reserva", 300000, None, 50000)
    b = finance.month_budget(c, "2026-11")
    assert b.goals == 50000 and b.available == before - 50000
    ops.deposit_goal(c, gid, 50000, TODAY)
    b = finance.month_budget(c, "2026-11")
    assert b.goals == 50000 and b.spent == 0 and b.available == before - 50000  # não conta duas vezes
    ops.deposit_goal(c, gid, 20000, TODAY)
    assert finance.month_budget(c, "2026-11").goals == 70000
    g = finance.goals_overview(c, TODAY)[0]
    assert g["saved_cents"] == 70000 and g["left_cents"] == 230000 and g["due_this_month_cents"] == 0


def test_goal_finished_stops_reserving(c):
    from forca import ops

    _setup(c)
    gid = ops.add_goal(c, "Viagem", 100000, None, 60000)
    ops.deposit_goal(c, gid, 100000, TODAY)
    g = finance.goals_overview(c, TODAY)[0]
    assert g["done"] and g["left_cents"] == 0
    assert finance.month_budget(c, "2026-12").goals == 0


def test_goal_monthly_from_due_date_and_forecast(c, monkeypatch):
    from forca import config, ops

    monkeypatch.setattr(config, "today", lambda: TODAY)
    gid = ops.add_goal(c, "Carro", 100000, "2027-02")  # nov, dez, jan, fev = 4 meses
    g = finance.goals_overview(c, TODAY)[0]
    assert g["monthly_cents"] == 25000 and g["on_time"] is True
    ops.update_goal(c, gid, "Carro", 100000, "2027-02", 10000)
    g = finance.goals_overview(c, TODAY)[0]
    assert g["monthly_cents"] == 10000 and g["on_time"] is False


def test_goal_withdraw_limits(c):
    from forca import ops

    gid = ops.add_goal(c, "Reserva", 100000)
    ops.deposit_goal(c, gid, 30000, TODAY)
    with pytest.raises(ops.Invalid):
        ops.deposit_goal(c, gid, -40000, TODAY)
    ops.deposit_goal(c, gid, -10000, TODAY)
    assert finance.goals_overview(c, TODAY)[0]["saved_cents"] == 20000
    with pytest.raises(ops.Invalid):
        ops.add_goal(c, "X", 100, "junho")


def test_guardei_text(c):
    from forca import ops

    assert ops.capture(c, "guardei 200", TODAY, "t") is None  # sem meta: vai para a agente
    assert not c.execute("SELECT 1 FROM transactions").fetchone()
    ops.add_goal(c, "Reserva de emergência", 500000)
    ops.add_goal(c, "Viagem", 500000)
    r = ops.capture(c, "guardei 200 na reserva", TODAY, "t")
    assert r["type"] == "goal" and r["goal"] == "Reserva de emergência" and r["saved_cents"] == 20000
    assert ops.capture(c, "poupei 100 pra viagem", TODAY, "t")["goal"] == "Viagem"
    assert ops.capture(c, "guardei 100", TODAY, "t") is None  # duas metas: ambíguo


def test_past_month_goal_counts_only_deposits(c):
    from forca import config, ops

    _setup(c)
    ops.add_goal(c, "Reserva", 900000, None, 50000)
    past = finance.add_months(finance.month_of(config.today()), -1)
    assert finance.month_budget(c, past).goals == 0


def test_suggested_reserve(c):
    _setup(c)
    c.execute("INSERT INTO debts (name, balance_cents, min_payment_cents) VALUES ('D', 1000, 5000)")
    assert finance.suggested_reserve(c) == (160000 + 5000) * 3


# ---------- relatório ----------


def test_report_compares_months(c):
    _setup(c)
    ledger.add_expense(c, 10000, "Mercado", date(2026, 10, 5))
    ledger.add_expense(c, 5000, "Ifood", date(2026, 10, 6))
    ledger.add_expense(c, 30000, "Mercado", date(2026, 11, 5))
    ledger.add_expense(c, 2000, "Ifood", date(2026, 11, 6))
    ledger.add_expense(c, 90000, "Mercado grande", date(2026, 11, 29))
    r = finance.report(c, "2026-11", date(2026, 12, 2))
    assert r["spent_cents"] == 122000 and r["previous_spent_cents"] == 15000
    assert r["daily_average_cents"] == 122000 // 30 and r["is_current"] is False and r["can_go_next"] is True
    mercado = next(x for x in r["categories"] if x["category"] == "mercado")
    assert mercado["delta_cents"] == 110000 and mercado["label"] == "Mercado"
    assert r["top_expenses"][0]["amount_cents"] == 90000 and len(r["top_expenses"]) == 3
    assert any("107.000" in i["text"] or "1.070" in i["text"] for i in r["insights"])
    assert any("Mercado foi o que mais cresceu" in i["text"] for i in r["insights"])
    assert [h["month"] for h in r["history"]] == ["2026-10", "2026-11"]


def test_report_current_month_compares_same_period(c):
    _setup(c)
    ledger.add_expense(c, 10000, "Mercado", date(2026, 10, 5))
    ledger.add_expense(c, 90000, "Mercado", date(2026, 10, 25))
    ledger.add_expense(c, 12000, "Mercado", date(2026, 11, 5))
    r = finance.report(c, "2026-11", TODAY)
    assert r["is_current"] and "R$ 20 a mais" in r["insights"][0]["text"] and "até o dia 11" in r["insights"][0]["text"]


def test_report_empty_month(c):
    r = finance.report(c, "2026-11", TODAY)
    assert (
        r["spent_cents"] == 0 and r["top_expenses"] == [] and r["insights"] == [] and r["previous_spent_cents"] is None
    )


def test_report_flags_past_limit(c):
    from forca import ops

    _setup(c)
    ops.set_category_budget(c, "mercado", 5000)
    ledger.add_expense(c, 6000, "Mercado", TODAY)
    assert any("Passou do limite em: Mercado" in i["text"] for i in finance.report(c, "2026-11", TODAY)["insights"])
