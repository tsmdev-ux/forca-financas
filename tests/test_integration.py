import asyncio
import io
import json
from datetime import date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from forca import ai, backup, bot, config, db, finance, ledger, nudges, onboarding, web

TODAY = date(2026, 11, 11)
OWNER = 777


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "b")
    monkeypatch.setattr(config, "PASSWORD", "segredo")
    monkeypatch.setattr(config, "PAIR_CODE", "abc123")
    monkeypatch.setattr(config, "DEEPSEEK_KEY", "")
    monkeypatch.setattr(config, "today", lambda: TODAY)
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 11, 11, 12, 0, tzinfo=config.TZ))
    web._failures.clear()
    db.init()


# ---------- API ----------


@pytest.fixture()
def api(env):
    client = TestClient(web.app)
    assert client.post("/api/login", json={"password": "segredo"}).status_code == 200
    return client


def test_auth_required(env):
    client = TestClient(web.app)
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/export").status_code == 401
    assert client.post("/api/quick", json={"text": "x 1"}).status_code == 401
    assert client.post("/api/login", json={"password": "errada"}).status_code == 401
    client.cookies.set(web.COOKIE, "9999999999.assinaturafalsa")
    assert client.get("/api/state").status_code == 401


def test_login_throttle(env):
    client = TestClient(web.app)
    for _ in range(8):
        client.post("/api/login", json={"password": "x"})
    assert client.post("/api/login", json={"password": "segredo"}).status_code == 429


def test_public_files_and_headers(env):
    client = TestClient(web.app)
    r = client.get("/")
    assert r.status_code == 200 and "Content-Security-Policy" in r.headers
    assert client.get("/manifest.webmanifest").status_code == 200
    assert client.get("/sw.js").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/docs").status_code in (401, 404)


def test_old_statement_does_not_invent_overdue_bills(api):
    api.post("/api/recurring", json={"kind": "income", "name": "Salário", "amount_cents": 500000, "day": 5})
    api.post("/api/recurring", json={"kind": "expense", "name": "Aluguel", "amount_cents": 150000, "day": 20})
    csv = b"data;descricao;valor\n05/08/2026;PADARIA;-10,00\n06/08/2026;LOJA;-20,00\n"
    assert api.post("/api/import", files={"file": ("f.csv", csv)}).json()["added"] == 2
    s = api.get("/api/state").json()
    assert not [i for i in s["upcoming"] if i["days"] < 0]
    assert s["month"]["carry_cents"] == 0


def test_full_setup_and_daily_flow(api):
    assert api.get("/api/state").json()["daily"]["status"] == "setup"
    assert (
        api.post(
            "/api/recurring", json={"kind": "income", "name": "Salário", "amount_cents": 500000, "day": 5}
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/recurring", json={"kind": "expense", "name": "Aluguel", "amount_cents": 150000, "day": 20}
        ).status_code
        == 200
    )
    api.post("/api/cards", json={"name": "Nubank", "closing_day": 3, "due_day": 10, "opening_cents": 50000})
    api.post(
        "/api/debts",
        json={
            "name": "Empréstimo",
            "balance_cents": 300000,
            "monthly_rate": 4,
            "min_payment_cents": 30000,
            "due_day": 15,
        },
    )
    s = api.get("/api/state").json()
    # o cartão fecha dia 3 e hoje é dia 11: a fatura herdada vence em dezembro, não pesa em novembro
    assert s["month"]["available_cents"] == 500000 - 150000 - 30000
    assert s["cards"][0]["current_invoice_cents"] == 50000
    assert s["daily"]["status"] == "ok" and s["debts"]["free_month"]

    r = api.post("/api/quick", json={"text": "mercado 87,50"}).json()
    assert r["type"] == "expense" and r["category"] == "mercado" and "cabe" in r["message"]
    s2 = api.get("/api/state").json()
    assert s2["daily"]["spent_cents"] == 8750

    assert api.delete(f"/api/transactions/{r['id']}").json()["removed"] == 1
    assert api.get("/api/state").json()["daily"]["spent_cents"] == 0

    q = api.post("/api/quick", json={"text": "posso comprar um tênis de 900?"}).json()
    assert q["type"] == "assessment" and q["assessment"]["verdict"] in ("wait", "no")
    api.post("/api/purchase", json={"item": "Tênis", "amount_cents": 90000, "choice": "skip"})
    assert api.get("/api/state").json()["saved_cents"] == 90000

    rec = api.post("/api/quick", json={"text": "internet 120 todo dia 15"}).json()
    assert rec["type"] == "recurring"
    assert any(x["name"] == "Internet" for x in api.get("/api/state").json()["recurring"])


def test_categories_goals_report_api(api):
    r = api.post("/api/categories", json={"label": "Pilates", "icon": "🧘"})
    assert r.json()["key"] == "pilates"
    assert api.post("/api/budgets", json={"category": "pilates", "limit_cents": 20000}).status_code == 200
    assert api.post("/api/quick", json={"text": "pilates 90"}).json()["category"] == "pilates"
    s = api.get("/api/state").json()
    assert any(x["key"] == "pilates" for x in s["category_list"])
    report = api.get("/api/report").json()
    assert report["categories"][0]["label"] == "Pilates" and report["month"] == "2026-11"
    assert api.get("/api/report?month=2026-13").status_code == 422
    assert api.get("/api/report?month=2030-01").json()["month"] == "2026-11"  # futuro não existe

    goal = api.post("/api/goals", json={"name": "Reserva", "target_cents": 100000, "due_month": "2027-02"}).json()["id"]
    assert api.get("/api/state").json()["goals"][0]["monthly_cents"] == 25000
    dep = api.post(f"/api/goals/{goal}/deposits", json={"amount_cents": 25000}).json()["id"]
    assert api.get("/api/state").json()["goals"][0]["saved_cents"] == 25000
    q = api.post("/api/quick", json={"text": "guardei 100 na reserva"}).json()
    assert q["type"] == "goal" and "Reserva" in q["message"]
    api.delete(f"/api/goal-deposits/{dep}")
    assert api.get("/api/state").json()["goals"][0]["saved_cents"] == 10000
    assert api.post(f"/api/goals/{goal}/deposits", json={"amount_cents": -999999}).status_code == 422
    assert api.post("/api/goals", json={"name": "X", "target_cents": 100, "due_month": "ontem"}).status_code == 422
    api.delete(f"/api/goals/{goal}")
    assert api.get("/api/state").json()["goals"] == []
    assert api.delete("/api/categories/outros").status_code == 422
    assert api.delete("/api/categories/pilates").json()["moved"] == 1
    assert "goals" in json.loads(api.get("/api/export").content)


def test_quick_without_ai_explains(api):
    r = api.post("/api/quick", json={"text": "como saio das dívidas"})
    assert r.status_code == 422 and "Não entendi" in r.json()["detail"]


def test_validation_messages(api):
    r = api.post("/api/recurring", json={"kind": "expense", "name": "X", "amount_cents": 100, "day": 40})
    assert r.status_code == 422 and "dia" in r.json()["detail"]
    r = api.post(
        "/api/debts",
        json={"name": "X", "balance_cents": 100, "monthly_rate": 500, "min_payment_cents": 1, "due_day": 1},
    )
    assert r.status_code == 422


def test_import_endpoint_and_undo(api):
    api.post("/api/cards", json={"name": "A", "closing_day": 3, "due_day": 10})
    api.post("/api/cards", json={"name": "B", "closing_day": 3, "due_day": 10})
    csv = b"date,title,amount\n2026-11-02,Padaria,23.50\n2026-11-03,Livro,50.00\n"
    r = api.post("/api/import", files={"file": ("f.csv", csv)})
    assert r.status_code == 409 and r.json()["needs_card"]
    r = api.post("/api/import", files={"file": ("f.csv", csv)}, data={"card_id": r.json()["cards"][0]["id"]}).json()
    assert r["added"] == 2
    assert api.post(f"/api/import/{r['batch_id']}/undo").json()["removed"] == 2
    assert api.post("/api/import", files={"file": ("f.xlsx", b"x")}).status_code == 422


def test_transaction_update_and_learning(api):
    tx = api.post("/api/quick", json={"text": "lojinha 40"}).json()
    r = api.put(
        f"/api/transactions/{tx['id']}",
        json={"description": "Lojinha", "amount_cents": 4500, "date": "2026-11-10", "category": "compras"},
    )
    assert r.status_code == 200
    assert api.post("/api/quick", json={"text": "lojinha 10"}).json()["category"] == "compras"


def test_simulate_and_export(api):
    api.post(
        "/api/debts",
        json={"name": "D", "balance_cents": 100000, "monthly_rate": 2, "min_payment_cents": 10000, "due_day": 15},
    )
    a = api.get("/api/debts-simulate?extra_cents=0").json()
    b = api.get("/api/debts-simulate?extra_cents=50000").json()
    assert b["months"] < a["months"] and b["free_month"]
    assert json.loads(api.get("/api/export").content)["debts"][0]["name"] == "D"


# ---------- bot ----------


class FakeTelegram:
    def __init__(self):
        self.calls = []

    async def api(self, method, **p):
        self.calls.append((method, p))
        return {}

    async def send(self, chat, text, markup=None):
        self.calls.append(("send", {"chat": chat, "text": text, "markup": markup}))

    async def download(self, file_id):
        return self.files[file_id]

    @property
    def texts(self):
        return [p["text"] for m, p in self.calls if m in ("send", "editMessageText")]


@pytest.fixture()
def tg(env):
    return FakeTelegram()


@pytest.fixture()
def b(tg):
    return bot.Bot(tg)


def msg(text, chat=OWNER):
    return {"message": {"chat": {"id": chat}, "text": text}}


def press(data, chat=OWNER):
    return {"callback_query": {"id": "1", "data": data, "message": {"message_id": 5, "chat": {"id": chat}}}}


def run(coro):
    return asyncio.run(coro)


def pair(b):
    run(b.handle(msg("/start abc123")))
    with db.tx() as c:
        onboarding.cancel(c)  # os testes abaixo falam com o bot já cadastrado


def button_data(tg):
    last = [p for m, p in tg.calls if m == "send" and p["markup"]][-1]
    return [btn["callback_data"] for row in last["markup"].get("inline_keyboard", []) for btn in row]


def test_pairing_and_strangers(b, tg):
    run(b.handle(msg("/start errado", chat=1)))
    run(b.handle(msg("mercado 50", chat=1)))
    assert tg.calls == []
    pair(b)
    assert "Oi" in tg.texts[0]
    n = len(tg.calls)
    run(b.handle(msg("/start abc123", chat=2)))  # dono já definido: código não vale mais
    run(b.handle(msg("mercado 50", chat=2)))
    run(b.handle(press("undo:1", chat=2)))
    assert len(tg.calls) == n
    with db.tx() as c:
        assert db.get_setting(c, "owner_chat_id") == str(OWNER)
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_setup_by_chat_then_log_and_undo(b, tg):
    pair(b)
    run(b.handle(msg("ganho 3000 todo dia 5")))
    run(b.handle(msg("aluguel 1000 todo dia 20")))
    with db.tx() as c:
        rows = {r["kind"]: r["name"] for r in c.execute("SELECT * FROM recurring")}
    assert rows == {"income": "Salário", "expense": "Aluguel"}
    run(b.handle(msg("mercado 87")))
    assert any("Mercado R$ 87" in t and "cabe" in t for t in tg.texts)
    data = button_data(tg)
    undo = next(d for d in data if d.startswith("undo:"))
    run(b.handle(press(undo)))
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_fixed_bill_and_paid_without_amount(b, tg):
    pair(b)
    run(b.handle(msg("ganho 3000 todo dia 5")))
    run(b.handle(msg("aluguel 1000 todo dia 20")))
    run(b.handle(msg("paguei o aluguel")))
    assert any("Aluguel marcada como paga" in t for t in tg.texts)
    with db.tx() as c:
        assert finance.month_budget(c, "2026-11").fixed == 100000
        assert finance.month_budget(c, "2026-11").spent == 0


def test_absurd_value_is_checked_before_saving(b, tg):
    pair(b)
    run(b.handle(msg("televisão 4000000")))
    assert any("Só para conferir" in t for t in tg.texts)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    data = button_data(tg)
    run(b.handle(press(next(d for d in data if d.startswith("chkno:")))))
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    run(b.handle(msg("televisão 4000000")))
    run(b.handle(press(next(d for d in button_data(tg) if d.startswith("chk:")))))
    with db.tx() as c:
        assert c.execute("SELECT amount_cents FROM transactions").fetchone()[0] == 400000000


def test_delete_request_reaches_agent_not_ledger(b, tg, monkeypatch):
    pair(b)
    seen = []

    async def fake_chat(text, today):
        seen.append(text)
        return "Certo."

    monkeypatch.setattr(bot.ai, "enabled", lambda: True)
    monkeypatch.setattr(bot.ai, "chat", fake_chat)
    run(b.handle(msg("exclui essa conta de 4000")))
    assert seen == ["exclui essa conta de 4000"]
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_buttons_change_category_and_card(b, tg):
    pair(b)
    with db.tx() as c:
        c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'A', 3, 10), (2, 'B', 20, 28)")
    run(b.handle(msg("lojinha 100 no cartão")))
    data = button_data(tg)
    assert "Em qual cartão?" in tg.texts[-1]
    run(b.handle(press(next(d for d in data if d.endswith(":2") and d.startswith("setcard")))))
    with db.tx() as c:
        row = c.execute("SELECT * FROM transactions").fetchone()
    assert row["card_id"] == 2 and row["invoice_month"] == "2026-11"
    tx = row["id"]
    run(b.handle(press(f"setcat:{tx}:compras")))
    run(b.handle(msg("lojinha 20")))
    with db.tx() as c:
        assert c.execute("SELECT category FROM transactions ORDER BY id DESC LIMIT 1").fetchone()[0] == "compras"


def test_impulse_brake_flow(b, tg):
    pair(b)
    run(b.handle(msg("ganho 3000 todo dia 5")))
    run(b.handle(msg("posso comprar um tênis de 900?")))
    assert any("eu esperaria" in t for t in tg.texts)
    data = button_data(tg)
    run(b.handle(press(next(d for d in data if d.startswith("p24:")))))
    with db.tx() as c:
        pause = c.execute("SELECT * FROM pauses").fetchone()
    assert pause["status"] == "waiting"

    # 24h depois, o lembrete sai uma vez só
    sent = []

    async def send(chat, text, markup):
        sent.append((text, markup))

    later = datetime(2026, 11, 12, 13, 0, tzinfo=config.TZ)
    run(nudges.tick(send, OWNER, later))
    run(nudges.tick(send, OWNER, later))
    reminders = [s for s in sent if "ainda quer" in s[0]]
    assert len(reminders) == 1
    run(b.handle(press(f"pzno:{pause['id']}")))
    with db.tx() as c:
        assert finance.saved_by_pauses(c) == 90000


def test_file_import_via_bot(b, tg):
    pair(b)
    tg.files = {"f1": b"data;descricao;valor\n05/11/2026;PADARIA;-10,00\n06/11/2026;FARMACIA;-20,00\n"}
    run(
        b.handle(
            {
                "message": {
                    "chat": {"id": OWNER},
                    "document": {"file_id": "f1", "file_name": "e.csv", "mime_type": "text/csv"},
                }
            }
        )
    )
    assert any("2 novos" in t for t in tg.texts)
    data = button_data(tg)
    run(b.handle(press(data[0])))
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_voice_goes_through_text_flow(b, tg, monkeypatch):
    pair(b)
    tg.files = {"v": b"ogg"}

    async def fake(raw):
        return "uber 25 reais"

    monkeypatch.setattr(bot.transcribe, "transcribe", fake)
    run(b.handle({"message": {"chat": {"id": OWNER}, "voice": {"file_id": "v"}}}))
    with db.tx() as c:
        assert c.execute("SELECT amount_cents FROM transactions").fetchone()[0] == 2500


def test_bot_reports_goals_limits_categories(b, tg):
    pair(b)
    run(b.handle(msg("mercado 87")))
    for text in ("/relatorio", "Relatório", "/metas", "/limites", "/categorias"):
        run(b.handle(msg(text)))
    joined = "\n".join(tg.texts)
    assert (
        "Relatório de novembro" in joined
        and "Nenhuma meta" in joined
        and "Nenhum limite" in joined
        and "Pets" in joined
    )
    with db.tx() as c:
        from forca import ops

        ops.add_goal(c, "Reserva", 100000)
    run(b.handle(msg("guardei 200 na reserva")))
    assert any("Guardado: R$ 200" in t for t in tg.texts)
    run(b.handle(press(button_data(tg)[0])))
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM goal_deposits").fetchone()[0] == 0


def test_agent_can_create_category_and_goal(env):
    seen = []
    client = fake_client(
        [
            (
                {
                    "content": None,
                    "tool_calls": [
                        call("t1", "add_category", {"label": "Pilates", "icon": "🧘"}),
                        call("t2", "add_goal", {"name": "Reserva", "target": 3000, "monthly": 500}),
                        call("t3", "deposit_goal", {"goal_id": 1, "amount": 100}),
                        call("t4", "add_expense", {"amount": 90, "description": "Aula", "category": "pilates"}),
                        call("t5", "add_expense", {"amount": 10, "description": "X", "category": "inventada"}),
                        call("t6", "get_report", {}),
                    ],
                },
                "tool_calls",
            ),
            ({"content": "ok"}, "stop"),
        ],
        seen,
    )
    assert run(ai.chat("x", TODAY, client)) == "ok"
    results = seen[1]["body"]["messages"][-6:]
    assert all(not r["content"].startswith("Erro") for r in results[:4])
    assert results[4]["content"].startswith("Erro: Categoria desconhecida") and "gastou" in results[5]["content"]
    with db.tx() as c:
        assert c.execute("SELECT category FROM transactions").fetchone()[0] == "pilates"
        assert finance.goals_overview(c, TODAY)[0]["saved_cents"] == 10000


def test_goal_reminder_once_a_month(env):
    from forca import ops

    seed_basic()
    with db.tx() as c:
        ledger.add_expense(c, 100, "x", TODAY)
        ops.add_goal(c, "Reserva", 100000, None, 20000)
    assert any("falta guardar" in t for t, _ in collect_at(at(10, 40)))
    assert not any("falta guardar" in t for t, _ in collect_at(at(10, 41)))


def talk(b, *answers):
    for a in answers:
        run(b.handle(msg(a)))


def test_onboarding_full_conversation(b, tg):
    run(b.handle(msg("/start abc123")))
    assert any("Quanto você ganha" in t for t in tg.texts)
    talk(b, "mercado 50")  # engano: não vira renda
    assert "Não entendi o valor" in tg.texts[-1]
    talk(b, "4 mil", "99", "10")  # dia inválido pergunta de novo
    assert any("Não entendi o dia" in t for t in tg.texts)
    assert any("Anotado: R$ 4.000 todo dia 10" in t for t in tg.texts)
    run(b.handle(press("ob:Aluguel")))
    talk(b, "1.200", "20", "internet 110 todo dia 15")
    assert any("Internet" in t and "Anotado" in t for t in tg.texts)
    assert "Aluguel" not in str(button_data(tg))  # já cadastrado sai das opções
    run(b.handle(press("ob:terminei")))
    run(b.handle(press("ob:sim")))
    run(b.handle(press("ob:Nubank")))
    talk(b, "3", "10", "1800")
    run(b.handle(press("ob:sim")))
    run(b.handle(press("ob:Inter")))
    talk(b, "20", "28")
    run(b.handle(press("ob:pular")))
    run(b.handle(press("ob:nao")))
    run(b.handle(press("ob:sim")))
    talk(b, "Rotativo", "5000", "14%", "300", "10")
    run(b.handle(press("ob:sim")))  # em atraso
    run(b.handle(press("ob:nao")))  # sem mais dívidas
    assert any("Pronto, o básico" in t for t in tg.texts)
    with db.tx() as c:
        assert not onboarding.active(c)
        income = c.execute("SELECT name, amount_cents, day FROM recurring WHERE kind='income'").fetchone()
        assert tuple(income) == ("Salário", 400000, 10)
        assert {
            r["name"]: (r["amount_cents"], r["day"]) for r in c.execute("SELECT * FROM recurring WHERE kind='expense'")
        } == {"Aluguel": (120000, 20), "Internet": (11000, 15)}
        assert [r["name"] for r in c.execute("SELECT name FROM cards ORDER BY id")] == ["Nubank", "Inter"]
        assert finance.invoice_total(c, 1, "2026-12") == 180000
        d = c.execute("SELECT * FROM debts").fetchone()
        assert (
            d["name"],
            d["balance_cents"],
            d["monthly_rate"],
            d["min_payment_cents"],
            d["due_day"],
            d["overdue"],
        ) == ("Rotativo", 500000, 14.0, 30000, 10, 1)
        assert c.execute("SELECT COUNT(*) FROM transactions WHERE source != 'opening'").fetchone()[0] == 0
    talk(b, "mercado 87")  # voltou ao normal
    assert any("Mercado R$ 87" in t for t in tg.texts)


def test_onboarding_checks_absurd_value_and_survives_restart(b, tg):
    run(b.handle(msg("/start abc123")))
    talk(b, "4.000.000")
    assert "Só para conferir" in tg.texts[-1]
    other = bot.Bot(tg)  # reinício no meio da conversa
    run(other.handle(press("ob:corrigir")))
    assert "Qual é o valor" in tg.texts[-1]
    talk(other, "4000")
    assert "Em que dia" in tg.texts[-1]
    talk(other, "10")
    with db.tx() as c:
        assert c.execute("SELECT amount_cents FROM recurring").fetchone()[0] == 400000
    talk(other, "cancelar")
    with db.tx() as c:
        assert not onboarding.active(c)


def test_onboarding_commands_still_work_and_restart_skips_income(b, tg):
    run(b.handle(msg("/start abc123")))
    talk(b, "4000", "hoje")  # botão do teclado não vira resposta
    assert any("pode gastar" in t or "renda" in t or "limite" in t for t in tg.texts)
    with db.tx() as c:
        assert onboarding.active(c)
    talk(b, "10", "cancelar", "/comecar")
    assert any("Sua renda já está aqui" in t for t in tg.texts)


def test_keyboard_has_three_buttons(b, tg):
    run(b.handle(msg("/start abc123")))
    keyboards = [
        p["markup"]["keyboard"] for m, p in tg.calls if m == "send" and p["markup"] and "keyboard" in p["markup"]
    ]
    assert [[k["text"] for k in row] for row in keyboards[0]] == [["Hoje", "Pagar", "Metas"]]


# ---------- backup externo ----------


def test_backup_round_trip():
    blob = backup.encrypt(b"dados financeiros", "senha certa")
    assert b"dados financeiros" not in blob and blob.startswith(b"FORCA1")
    assert backup.decrypt(blob, "senha certa") == b"dados financeiros"
    with pytest.raises(backup.WrongPassword):
        backup.decrypt(blob, "senha errada")
    with pytest.raises(backup.WrongPassword):
        backup.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), "senha certa")
    with pytest.raises(backup.WrongPassword):
        backup.decrypt(b"qualquer coisa", "x")


def test_offsite_backup_is_weekly_encrypted_and_restorable(env, tmp_path):
    import sqlite3

    nudges._offsite_retry_at = None
    with db.tx() as c:
        ledger.add_expense(c, 12345, "Marcador secreto", TODAY)
    sent = []

    async def send_document(chat, name, data, caption):
        sent.append((chat, name, data))

    now = at(10)
    assert run(nudges.offsite_backup(send_document, OWNER, now)) is True
    assert run(nudges.offsite_backup(send_document, OWNER, at(11))) is False
    assert run(nudges.offsite_backup(send_document, OWNER, datetime(2026, 11, 18, 10, 30, tzinfo=config.TZ))) is True
    assert len(sent) == 2 and sent[0][1] == "forca-2026-11-11.forca"
    assert b"Marcador secreto" not in sent[0][2]
    restored = tmp_path / "r.db"
    restored.write_bytes(backup.decrypt(sent[0][2], "segredo"))
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT description FROM transactions").fetchone()[0] == "Marcador secreto"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_offsite_backup_retries_after_failure(env):
    nudges._offsite_retry_at = None
    calls = []

    async def fails(chat, name, data, caption):
        calls.append(1)
        raise RuntimeError("sem rede")

    assert run(nudges.offsite_backup(fails, OWNER, at(10))) is False
    assert run(nudges.offsite_backup(fails, OWNER, at(10, 30))) is False  # espera 1 hora
    assert len(calls) == 1
    with db.tx() as c:
        assert not db.get_setting(c, "offsite_backup_at")
    assert run(nudges.offsite_backup(fails, OWNER, at(11, 1))) is False
    assert len(calls) == 2
    nudges._offsite_retry_at = None


def test_unknown_without_ai_helps(b, tg):
    pair(b)
    run(b.handle(msg("como saio das dívidas")))
    assert "Não entendi" in tg.texts[-1]


def test_html_in_description_is_escaped(b, tg):
    pair(b)
    run(b.handle(msg("<b>x</b> 50")))
    assert "&lt;b&gt;" in tg.texts[-1] and "<b>x" not in tg.texts[-1]


# ---------- avisos ----------


def at(h, m=0, d=TODAY):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=config.TZ)


def collect_at(when):
    with db.tx() as c:
        return nudges.collect(c, when)


def seed_basic():
    with db.tx() as c:
        c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('income', 'Salário', 500000, 5)")
        c.execute("INSERT INTO recurring (kind, name, amount_cents, day) VALUES ('expense', 'Internet', 10000, 11)")
        ledger.ensure_started(c, date(2026, 11, 1))


def test_morning_once_and_quiet_hours(env):
    seed_basic()
    assert collect_at(at(6)) == []  # madrugada: nada
    first = collect_at(at(8, 1))
    assert any("Hoje você pode gastar" in t for t, _ in first)
    assert not any("pode gastar" in t for t, _ in collect_at(at(8, 2)))  # não repete
    assert collect_at(at(23)) == []


def test_restart_does_not_send_stale_morning(env):
    seed_basic()
    assert not any("pode gastar" in t for t, _ in collect_at(at(15)))


def test_due_today_reminder(env):
    seed_basic()
    out = collect_at(at(18, 5))
    assert any("Internet" in t and "vence hoje" in t for t, _ in out)
    assert not any("vence hoje" in t for t, _ in collect_at(at(18, 6)))


def test_alert_one_day_before_due(env):
    """Internet vence dia 11: o alerta sai no dia 10, uma vez, e cobre conta, fatura e dívida."""
    seed_basic()
    with db.tx() as c:
        c.execute("INSERT INTO cards (id, name, closing_day, due_day) VALUES (1, 'Nubank', 3, 11)")
        c.execute(
            "INSERT INTO debts (id, name, balance_cents, min_payment_cents, due_day) VALUES (1, 'Empréstimo', 100000, 20000, 11)"
        )
        card = c.execute("SELECT * FROM cards").fetchone()
        ledger.add_expense(c, 5000, "Loja", date(2026, 11, 1), card=card)
    day_before = date(2026, 11, 10)
    assert not any("vence amanhã" in t for t, _ in collect_at(at(8, 30, day_before)))
    out = [(t, m) for t, m in collect_at(at(9, 5, day_before)) if "vence amanhã" in t]
    assert {t.split("</b>")[0].split("<b>")[1] for t, _ in out} == {"Internet", "Fatura Nubank", "Empréstimo"}
    assert any("R$ 100" in t and "Internet" in t for t, _ in out)
    assert all("Já paguei" in str(m) and "paid:" in str(m) for _, m in out)
    assert not any("vence amanhã" in t for t, _ in collect_at(at(9, 6, day_before)))  # não repete


def test_no_alert_for_paid_bill_or_muted(env):
    seed_basic()
    day_before = date(2026, 11, 10)
    with db.tx() as c:
        bill = c.execute("SELECT id FROM recurring WHERE kind = 'expense'").fetchone()["id"]
        ledger.mark_paid(c, "bill", bill, "2026-11", day_before)
    assert not any("vence amanhã" in t for t, _ in collect_at(at(9, 5, day_before)))
    with db.tx() as c:
        c.execute("DELETE FROM transactions")
        c.execute("DELETE FROM nudge_log")
        db.set_setting(c, "nudges_off", "1")
    assert collect_at(at(9, 5, day_before)) == []


def test_morning_does_not_repeat_tomorrow(env):
    seed_basic()
    out = collect_at(at(8, 1, date(2026, 11, 10)))
    assert any("pode gastar" in t and "Internet" not in t for t, _ in out)
    with db.tx() as c:
        assert "Internet" in bot.today_message(c, date(2026, 11, 10))[0]  # /hoje continua mostrando


def test_evening_prompt_only_without_logs(env):
    seed_basic()
    with db.tx() as c:
        ledger.add_expense(c, 100, "x", date(2026, 11, 10))
    out = collect_at(at(20, 35))
    assert any("Foi zero" in str(m) for _, m in out)
    with db.tx() as c:
        c.execute("DELETE FROM nudge_log")
        ledger.add_expense(c, 100, "y", TODAY)
    assert not any("Foi zero" in str(m) for _, m in collect_at(at(20, 35)))


def test_soft_cap_and_mute(env):
    seed_basic()
    with db.tx() as c:
        ledger.add_expense(c, 100, "x", date(2026, 11, 10))
        for i in range(nudges.MAX_SOFT_PER_DAY):
            c.execute("INSERT INTO nudge_log (key, sent_at) VALUES (?, 'x')", (f"soft:{TODAY.isoformat()}:n{i}",))
    assert not any("Foi zero" in str(m) for _, m in collect_at(at(20, 35)))
    with db.tx() as c:
        db.set_setting(c, "nudges_off", "1")
    assert collect_at(at(8, 1)) == []


def test_month_close_accrues_interest_once(env):
    with db.tx() as c:
        c.execute(
            "INSERT INTO debts (name, balance_cents, monthly_rate, min_payment_cents) VALUES ('D', 100000, 10, 0)"
        )
        db.set_setting(c, "started_month", "2026-11")
    sent = []

    async def send(chat, text, markup):
        sent.append(text)

    first = at(9, 0, date(2026, 12, 1))
    run(nudges.tick(send, None, first))  # sem Telegram: juros aplicam mesmo assim
    run(nudges.tick(send, OWNER, first))
    with db.tx() as c:
        assert c.execute("SELECT balance_cents FROM debts").fetchone()[0] == 110000


def test_starting_on_last_day_of_month(env, monkeypatch):
    """Primeiro uso em 31/10: nada de atraso inventado, juros de um dia ou déficit herdado."""
    last_day = date(2026, 10, 31)
    monkeypatch.setattr(config, "today", lambda: last_day)
    client = TestClient(web.app)
    client.post("/api/login", json={"password": "segredo"})
    client.post("/api/recurring", json={"kind": "income", "name": "Salário", "amount_cents": 300000, "day": 5})
    client.post("/api/recurring", json={"kind": "expense", "name": "Aluguel", "amount_cents": 350000, "day": 10})
    client.post(
        "/api/debts",
        json={
            "name": "Rotativo",
            "balance_cents": 500000,
            "monthly_rate": 14,
            "min_payment_cents": 30000,
            "due_day": 10,
        },
    )
    s = client.get("/api/state").json()
    assert not [i for i in s["upcoming"] if i["days"] < 0]
    assert s["focus"] is None and s["daily"]["status"] == "starting"

    sent = []

    async def send(chat, text, markup):
        sent.append(text)

    first = at(9, 0, date(2026, 11, 1))
    run(nudges.tick(send, OWNER, first))
    with db.tx() as c:
        assert c.execute("SELECT balance_cents FROM debts").fetchone()[0] == 500000
        assert finance.month_budget(c, "2026-11").carry == 0
    assert not any("fechou" in t for t in sent)
    # o aluguel de novembro já é cobrado normalmente
    with db.tx() as c:
        assert [i["days"] for i in finance.upcoming(c, date(2026, 11, 12), 3) if i["name"] == "Aluguel"] == [-2]


def test_weekly_summary_sunday(env):
    seed_basic()
    with db.tx() as c:
        ledger.add_expense(c, 5000, "Mercado", date(2026, 11, 13))
    sent = []

    async def send(chat, text, markup):
        sent.append(text)

    sunday = at(19, 5, date(2026, 11, 15))
    run(nudges.tick(send, OWNER, sunday))
    run(nudges.tick(send, OWNER, sunday))
    assert len([s for s in sent if "Sua semana" in s]) == 1


def test_backup_keeps_14(env):
    for day in range(1, 21):
        nudges.backup(datetime(2026, 11, day, 4, tzinfo=config.TZ))
    assert len(list(config.BACKUP_DIR.glob("*.db"))) == 14


# ---------- agente (API simulada) ----------


def fake_client(script, seen, status=200):
    """Responde com a lista `script` em ordem e guarda cada requisição."""
    steps = iter(script)

    def handler(request):
        seen.append({"body": json.loads(request.content), "headers": dict(request.headers), "path": request.url.path})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "x"}})
        message, finish = next(steps)
        return httpx.Response(
            200, json={"choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}]}
        )

    return httpx.AsyncClient(base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler))


def call(id_, name, args):
    return {
        "id": id_,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args) if not isinstance(args, str) else args},
    }


def test_agent_runs_tools_and_answers(env, monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_KEY", "chave")
    seen = []
    client = fake_client(
        [
            (
                {
                    "content": None,
                    "tool_calls": [
                        call("t1", "add_recurring", {"kind": "income", "name": "Salário", "amount": 4200, "day": 5}),
                        call(
                            "t2",
                            "add_debt",
                            {
                                "name": "Rotativo",
                                "balance": 5000,
                                "monthly_rate": 14,
                                "min_payment": 300,
                                "due_day": 10,
                                "overdue": False,
                            },
                        ),
                    ],
                },
                "tool_calls",
            ),
            ({"content": "", "tool_calls": [call("t3", "get_overview", {})]}, "tool_calls"),
            ({"content": "Pronto, cadastrei."}, "stop"),
        ],
        seen,
    )
    assert run(ai.chat("ganho 4200 e devo 5000 no rotativo", TODAY, client)) == "Pronto, cadastrei."
    with db.tx() as c:
        assert c.execute("SELECT amount_cents FROM recurring").fetchone()[0] == 420000
        assert c.execute("SELECT balance_cents FROM debts").fetchone()[0] == 500000
        assert c.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0] == 2

    first = seen[0]
    assert first["path"] == "/chat/completions" and first["headers"]["authorization"] == "Bearer chave"
    assert first["body"]["model"] == "deepseek-flash" and first["body"]["thinking"] == {"type": "disabled"}
    assert first["body"]["messages"][0]["role"] == "system"
    for tool in first["body"]["tools"]:
        assert tool["type"] == "function"
        schema = tool["function"]["parameters"]
        assert set(schema["required"]) <= set(schema["properties"])
        assert all(
            not isinstance(p.get("type"), list) and None not in p.get("enum", []) for p in schema["properties"].values()
        )
    # cada resultado volta como mensagem própria, depois da mensagem com as chamadas
    second = seen[1]["body"]["messages"]
    assert [m["role"] for m in second[-3:]] == ["assistant", "tool", "tool"]
    assert [m["tool_call_id"] for m in second[-2:]] == ["t1", "t2"]
    overview = json.loads(seen[2]["body"]["messages"][-1]["content"])
    assert overview["dividas"]["total"] == "R$ 5.000" and overview["mes"]["renda"] == "R$ 4.200"


def test_agent_optional_fields_can_be_omitted(env):
    client = fake_client(
        [
            (
                {"content": None, "tool_calls": [call("t1", "add_expense", {"amount": 30, "description": "Padaria"})]},
                "tool_calls",
            ),
            ({"content": "ok"}, "stop"),
        ],
        [],
    )
    assert run(ai.chat("x", TODAY, client)) == "ok"
    with db.tx() as c:
        row = c.execute("SELECT * FROM transactions").fetchone()
    assert row["amount_cents"] == 3000 and row["date"] == TODAY.isoformat()


def test_agent_bad_arguments_go_back_to_model(env):
    seen = []
    client = fake_client(
        [
            (
                {
                    "content": None,
                    "tool_calls": [
                        call("t1", "add_recurring", {"kind": "income", "name": "X", "amount": 100, "day": 99}),
                        call("t2", "get_overview", "{quebrado"),
                        call("t3", "add_debt", {"name": "faltam campos"}),
                        call("t4", "nao_existe", {}),
                    ],
                },
                "tool_calls",
            ),
            ({"content": "Qual o dia certo?"}, "stop"),
        ],
        seen,
    )
    assert run(ai.chat("x", TODAY, client)) == "Qual o dia certo?"
    results = seen[1]["body"]["messages"][-4:]
    assert all(r["role"] == "tool" and r["content"].startswith("Erro:") for r in results)
    assert "dia" in results[0]["content"]


def test_agent_filter_and_outages(env, monkeypatch):
    async def no_wait(_):
        return None

    monkeypatch.setattr(ai.asyncio, "sleep", no_wait)
    assert "outro jeito" in run(ai.chat("x", TODAY, fake_client([({"content": ""}, "content_filter")], [])))
    assert "recusada" in run(ai.chat("x", TODAY, fake_client([], [], status=401)))
    assert "saldo" in run(ai.chat("x", TODAY, fake_client([], [], status=402)))
    seen = []
    assert "continuam funcionando" in run(ai.chat("x", TODAY, fake_client([], seen, status=503)))
    assert len(seen) == 2  # repetiu uma vez

    def fail(request):
        raise httpx.ConnectError("sem rede")

    down = httpx.AsyncClient(base_url="https://x.test", transport=httpx.MockTransport(fail))
    assert "continuam funcionando" in run(ai.chat("x", TODAY, down))


def test_agent_history_starts_with_user(env):
    with db.tx() as c:
        c.execute("INSERT INTO chat_history (role, text) VALUES ('assistant', 'velho')")
        c.execute("INSERT INTO chat_history (role, text) VALUES ('user', 'oi')")
        c.execute("INSERT INTO chat_history (role, text) VALUES ('assistant', 'olá')")
    seen = []
    run(ai.chat("tudo bem?", TODAY, fake_client([({"content": "ok"}, "stop")], seen)))
    assert [m["role"] for m in seen[0]["body"]["messages"]] == ["system", "user", "assistant", "user"]
    assert seen[0]["body"]["messages"][-1]["content"].startswith("[hoje: 2026-11-11, quarta]")


# ---------- leitura de documentos ----------


def minimal_pdf(text):
    stream = f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 600 800]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % xref


DOC = {
    "kind": "card_invoice",
    "transactions": [
        {"date": "2026-11-05", "description": "Padaria", "amount": 23.5, "direction": "out"},
        {"date": "2026-11-06", "description": "Estorno", "amount": 10, "direction": "in"},
        {"date": "data ruim", "description": "Linha ruim", "amount": 1, "direction": "out"},
    ],
}


def test_extract_pdf_sends_text(env):
    seen = []
    client = fake_client([({"content": json.dumps(DOC)}, "stop")], seen)
    items, kind = run(ai.extract_document(minimal_pdf("Padaria 23,50"), "application/pdf", TODAY, client))
    assert kind == "card_invoice" and [(i.amount_cents, i.description) for i in items] == [
        (2350, "Padaria"),
        (-1000, "Estorno"),
    ]
    body = seen[0]["body"]
    assert body["response_format"] == {"type": "json_object"} and "tools" not in body
    assert "Padaria 23,50" in body["messages"][0]["content"] and "JSON" in body["messages"][0]["content"]


def test_extract_image_uses_data_url(env):
    seen = []
    client = fake_client([({"content": json.dumps(DOC)}, "stop")], seen)
    run(ai.extract_document(b"img", "image/jpeg", TODAY, client))
    part = seen[0]["body"]["messages"][0]["content"][0]
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_extract_retries_blank_json_then_fails_cleanly(env):
    client = fake_client([({"content": "  "}, "stop"), ({"content": json.dumps(DOC)}, "stop")], [])
    assert len(run(ai.extract_document(b"i", "image/png", TODAY, client))[0]) == 2
    client = fake_client([({"content": ""}, "stop"), ({"content": "nada"}, "stop")], [])
    with pytest.raises(ai.importers.ImportFailed):
        run(ai.extract_document(b"i", "image/png", TODAY, client))


def test_extract_pdf_problems_have_clear_messages(env):
    from pypdf import PdfWriter

    blank, locked = io.BytesIO(), io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.write(blank)
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("senha")
    w.write(locked)
    client = fake_client([], [])
    with pytest.raises(ai.importers.ImportFailed, match="só imagem"):
        run(ai.extract_document(blank.getvalue(), "application/pdf", TODAY, client))
    with pytest.raises(ai.importers.ImportFailed, match="senha"):
        run(ai.extract_document(locked.getvalue(), "application/pdf", TODAY, client))
    with pytest.raises(ai.importers.ImportFailed, match="abrir"):
        run(ai.extract_document(b"lixo", "application/pdf", TODAY, client))
