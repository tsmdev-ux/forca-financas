"""API e arquivos do PWA."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, config, db, finance, importers, ledger, ops, parser
from .finance import add_months, brl, month_of

STATIC = Path(__file__).parent / "static"
COOKIE = "forca_session"
SESSION_DAYS = 90
MAX_UPLOAD = 15 * 1024 * 1024

app = FastAPI(title="Força", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ops.Invalid)
async def invalid_handler(_: Request, exc: ops.Invalid) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=422)


# ---------- sessão ----------


def _secret() -> bytes:
    if config.SECRET:
        return config.SECRET.encode()
    with db.tx() as c:
        value = db.get_setting(c, "session_secret")
        if not value:
            value = secrets.token_hex(32)
            db.set_setting(c, "session_secret", value)
    return value.encode()


def _sign(expires: int) -> str:
    return hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()


def _valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    raw, signature = token.split(".", 1)
    if not raw.isdigit() or int(raw) < time.time():
        return False
    return hmac.compare_digest(signature, _sign(int(raw)))


def auth(request: Request) -> None:
    if not _valid_session(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Entre de novo.")


_failures: list[float] = []


class Login(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/login")
def login(body: Login, response: Response) -> dict:
    if not config.PASSWORD:
        raise HTTPException(503, "Defina FORCA_PASSWORD no servidor.")
    now = time.time()
    _failures[:] = [t for t in _failures if now - t < 300]
    if len(_failures) >= 8:
        raise HTTPException(429, "Muitas tentativas. Espere alguns minutos.")
    if not hmac.compare_digest(body.password.encode(), config.PASSWORD.encode()):
        _failures.append(now)
        raise HTTPException(401, "Senha incorreta.")
    expires = int(now) + SESSION_DAYS * 86400
    response.set_cookie(
        COOKIE,
        f"{expires}.{_sign(expires)}",
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=config.BASE_URL.startswith("https://"),
        path="/",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ---------- estado ----------


def _invoice_status(c, today: date, cards: list[dict]) -> None:
    for card in cards:
        for invoice in card["invoices"]:
            invoice["paid"] = (
                c.execute(
                    "SELECT 1 FROM invoice_payments WHERE card_id = ? AND invoice_month = ?",
                    (card["id"], invoice["month"]),
                ).fetchone()
                is not None
            )


def _tx_rows(c, where: str = "1=1", params: tuple = (), limit: int = 200) -> list[dict]:
    rows = c.execute(
        f"""SELECT t.*, cards.name AS card_name FROM transactions t LEFT JOIN cards ON cards.id = t.card_id
            WHERE {where} ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/state", dependencies=[Depends(auth)])
def state() -> dict:
    today = config.today()
    month = month_of(today)
    with db.tx() as c:
        t = finance.today_status(c, today)
        b = t.budget
        cards = finance.cards_overview(c, today)
        _invoice_status(c, today, cards)
        debts = finance.debts_overview(c, today)
        recurring = [dict(r) for r in c.execute("SELECT * FROM recurring WHERE active = 1 ORDER BY kind DESC, day")]
        for r in recurring:
            r["paid_this_month"] = (
                c.execute(
                    "SELECT 1 FROM transactions WHERE recurring_id = ? AND budget_month = ?", (r["id"], month)
                ).fetchone()
                is not None
            )
        pauses = [dict(r) for r in c.execute("SELECT * FROM pauses WHERE status = 'waiting' ORDER BY remind_at")]
        history = []
        for offset in range(-5, 1):
            m = add_months(month, offset)
            if c.execute(
                "SELECT 1 FROM transactions WHERE budget_month = ? AND kind = 'expense' LIMIT 1", (m,)
            ).fetchone():
                mb = finance.month_budget(c, m)
                history.append({"month": m, "spent_cents": mb.spent, "available_cents": mb.available})
        return {
            "today": today.isoformat(),
            "daily": {
                "status": t.status,
                "allowance_cents": t.daily_allowance,
                "spent_cents": t.spent_today,
                "left_cents": t.left_today,
                "tomorrow_cents": t.tomorrow,
                "days_left": t.days_left,
            },
            "month": {
                "month": month,
                "income_cents": b.income,
                "fixed_cents": b.fixed,
                "debts_cents": b.debts,
                "goals_cents": b.goals,
                "committed_cents": b.committed,
                "carry_cents": b.carry,
                "available_cents": b.available,
                "spent_cents": b.spent,
                "remaining_cents": b.remaining,
                "income_is_estimate": b.income_is_estimate,
                "projected_over_cents": finance.projected_month_end(c, today),
            },
            "focus": finance.focus(c, today),
            "upcoming": finance.upcoming(c, today, 35),
            "pace": finance.pace_series(c, month, today),
            "categories": finance.categories_for(c, month),
            "history": history,
            "cards": cards,
            "debts": debts,
            "recurring": recurring,
            "recent": _tx_rows(c, "t.budget_month <= ? AND t.date <= ?", (month, today.isoformat()), 12),
            "pauses": pauses,
            "saved_cents": finance.saved_by_pauses(c),
            "streak": finance.streak(c, today),
            "logged_today": c.execute(
                "SELECT 1 FROM transactions WHERE date = ? LIMIT 1", (today.isoformat(),)
            ).fetchone()
            is not None
            or c.execute("SELECT 1 FROM zero_days WHERE date = ?", (today.isoformat(),)).fetchone() is not None,
            "category_list": finance.category_list(c),
            "goals": finance.goals_overview(c, today),
            "reserve_suggestion_cents": finance.suggested_reserve(c),
            "settings": {
                "telegram": bool(config.TELEGRAM_TOKEN),
                "paired": bool(db.get_setting(c, "owner_chat_id")),
                "ai": ai.enabled(),
                "nudges_off": db.get_setting(c, "nudges_off") == "1",
                "morning_time": db.get_setting(c, "morning_time", "08:00"),
                "evening_time": db.get_setting(c, "evening_time", "20:30"),
                "bot_username": db.get_setting(c, "bot_username"),
                "pair_code": config.PAIR_CODE if not db.get_setting(c, "owner_chat_id") else None,
            },
        }


class Quick(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    confirmed: bool = False


@app.post("/api/quick", dependencies=[Depends(auth)])
async def quick(body: Quick) -> dict:
    """A mesma caixa do Telegram, no app."""
    today = config.today()
    question = parser.parse_purchase_question(body.text)
    if question:
        item, amount, installments = question
        with db.tx() as c:
            a = finance.assess_purchase(c, today, amount, installments)
        return {
            "type": "assessment",
            "item": item,
            "amount_cents": amount,
            "installments": installments,
            "assessment": a,
            "message": ops.assessment_text(item, a).replace("<b>", "").replace("</b>", ""),
        }
    with db.tx() as c:
        captured = ops.capture(c, body.text, today, "app", body.confirmed)
        if captured and captured["type"] == "check":
            return {
                "type": "check",
                "text": body.text,
                "message": f"Só para conferir: {brl(captured['amount_cents'])} em {captured['description']}. É isso mesmo? Ainda não registrei.",
            }
        if captured:
            if captured["type"] == "zero":
                message = f"Dia sem gasto. Sequência: {finance.streak(c, today)} dias."
            elif captured["type"] == "goal":
                message = ops.goal_text(captured)
            elif captured["type"] == "recurring":
                message = f"Cadastrado: {brl(captured['amount_cents'])} todo dia {captured['day']}."
            else:
                message = ops.feedback(c, today, captured.get("date") or today)
            ids = captured.get("ids") or []
            return {
                "type": captured["type"],
                "message": message,
                "id": ids[0] if ids else None,
                "category": captured.get("category"),
                "description": captured.get("description"),
                "amount_cents": captured.get("amount_cents"),
                "needs_card": captured.get("needs_card", False),
            }
    if not ai.enabled():
        raise HTTPException(422, 'Não entendi. Tente algo como "mercado 87" ou "tv 1200 10x nubank".')
    return {"type": "chat", "message": bot_plain(await ai.chat(body.text, today))}


def bot_plain(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")


class Purchase(BaseModel):
    item: str = Field(max_length=80)
    amount_cents: int = Field(gt=0)
    installments: int = Field(default=1, ge=1, le=72)
    choice: str


@app.post("/api/purchase", dependencies=[Depends(auth)])
def purchase(body: Purchase) -> dict:
    today = config.today()
    with db.tx() as c:
        if body.choice == "wait":
            ledger.create_pause(c, body.item, body.amount_cents, body.installments)
            return {"message": "Guardado por 24 horas."}
        pause = ledger.create_pause(c, body.item, body.amount_cents, body.installments)
        if body.choice == "skip":
            ledger.resolve_pause(c, pause, "skipped", today)
            return {"message": f"{brl(body.amount_cents)} ficaram com você."}
        if body.choice == "buy":
            ledger.resolve_pause(c, pause, "bought", today)
            return {"message": ops.feedback(c, today, today)}
    raise HTTPException(422, "Escolha inválida.")


class PauseAction(BaseModel):
    status: str


@app.post("/api/pauses/{pause_id}", dependencies=[Depends(auth)])
def pause_action(pause_id: int, body: PauseAction) -> dict:
    if body.status not in ("bought", "skipped"):
        raise HTTPException(422, "Status inválido.")
    with db.tx() as c:
        if ledger.resolve_pause(c, pause_id, body.status, config.today()) is None:
            raise HTTPException(404, "Essa pausa já foi resolvida.")
    return {"ok": True}


# ---------- lançamentos ----------


@app.get("/api/transactions", dependencies=[Depends(auth)])
def list_transactions(q: str = "", month: str = "", limit: int = 300) -> list:
    where, params = ["1=1"], []
    if q:
        where.append("t.description LIKE ?")
        params.append(f"%{q}%")
    if month:
        where.append("t.budget_month = ?")
        params.append(month)
    else:
        where.append("t.date <= ?")
        params.append(config.today().isoformat())
    with db.tx() as c:
        return _tx_rows(c, " AND ".join(where), tuple(params), min(limit, 1000))


class TxUpdate(BaseModel):
    description: str = Field(max_length=120)
    amount_cents: int = Field(gt=0)
    date: date
    category: str


@app.put("/api/transactions/{tx_id}", dependencies=[Depends(auth)])
def update_tx(tx_id: int, body: TxUpdate) -> dict:
    with db.tx() as c:
        ops.update_transaction(c, tx_id, body.description, body.amount_cents, body.date, body.category)
    return {"ok": True}


@app.delete("/api/transactions/{tx_id}", dependencies=[Depends(auth)])
def delete_tx(tx_id: int) -> dict:
    with db.tx() as c:
        removed = ledger.delete_transaction(c, tx_id)
    return {"removed": len(removed)}


class AssignCard(BaseModel):
    transaction_id: int
    card_id: int


@app.post("/api/assign-card", dependencies=[Depends(auth)])
def assign_card(body: AssignCard) -> dict:
    with db.tx() as c:
        ledger.assign_card(c, body.transaction_id, body.card_id)
    return {"ok": True}


class Paid(BaseModel):
    type: str
    id: int
    month: str
    amount_cents: int | None = Field(default=None, gt=0)


@app.post("/api/paid", dependencies=[Depends(auth)])
def paid(body: Paid) -> dict:
    today = config.today()
    with db.tx() as c:
        name = ledger.mark_paid(c, body.type, body.id, body.month, today, body.amount_cents)
    if name is None:
        raise HTTPException(404, "Não encontrei isso.")
    return {"name": name}


# ---------- cadastros ----------


class Recurring(BaseModel):
    kind: str
    name: str = Field(max_length=80)
    amount_cents: int
    day: int


@app.post("/api/recurring", dependencies=[Depends(auth)])
def create_recurring(body: Recurring) -> dict:
    with db.tx() as c:
        ledger.ensure_started(c, config.today())
        return {"id": ops.add_recurring(c, body.kind, body.name, body.amount_cents, body.day)}


@app.put("/api/recurring/{item_id}", dependencies=[Depends(auth)])
def edit_recurring(item_id: int, body: Recurring) -> dict:
    with db.tx() as c:
        ops.update_recurring(c, item_id, body.name, body.amount_cents, body.day)
    return {"ok": True}


@app.delete("/api/recurring/{item_id}", dependencies=[Depends(auth)])
def delete_recurring(item_id: int) -> dict:
    with db.tx() as c:
        ops.remove_recurring(c, item_id)
    return {"ok": True}


class Card(BaseModel):
    name: str = Field(max_length=80)
    closing_day: int
    due_day: int
    limit_cents: int | None = None
    opening_cents: int | None = None


@app.post("/api/cards", dependencies=[Depends(auth)])
def create_card(body: Card) -> dict:
    today = config.today()
    with db.tx() as c:
        ledger.ensure_started(c, today)
        card_id = ops.add_card(c, body.name, body.closing_day, body.due_day, body.limit_cents)
        if body.opening_cents:
            ledger.set_opening_invoice(c, card_id, ops.valid_amount(body.opening_cents), today)
        return {"id": card_id}


@app.put("/api/cards/{card_id}", dependencies=[Depends(auth)])
def edit_card(card_id: int, body: Card) -> dict:
    today = config.today()
    with db.tx() as c:
        ops.update_card(c, card_id, body.name, body.closing_day, body.due_day, body.limit_cents)
        if body.opening_cents:
            ledger.set_opening_invoice(c, card_id, ops.valid_amount(body.opening_cents), today)
    return {"ok": True}


@app.delete("/api/cards/{card_id}", dependencies=[Depends(auth)])
def delete_card(card_id: int) -> dict:
    with db.tx() as c:
        ops.remove_card(c, card_id)
    return {"ok": True}


class Debt(BaseModel):
    name: str = Field(max_length=80)
    balance_cents: int
    monthly_rate: float = 0
    min_payment_cents: int = 0
    due_day: int = 10
    overdue: bool = False


@app.post("/api/debts", dependencies=[Depends(auth)])
def create_debt(body: Debt) -> dict:
    with db.tx() as c:
        ledger.ensure_started(c, config.today())
        return {
            "id": ops.add_debt(
                c, body.name, body.balance_cents, body.monthly_rate, body.min_payment_cents, body.due_day, body.overdue
            )
        }


@app.put("/api/debts/{debt_id}", dependencies=[Depends(auth)])
def edit_debt(debt_id: int, body: Debt) -> dict:
    with db.tx() as c:
        ops.update_debt(
            c,
            debt_id,
            body.name,
            body.balance_cents,
            body.monthly_rate,
            body.min_payment_cents,
            body.due_day,
            body.overdue,
        )
    return {"ok": True}


@app.delete("/api/debts/{debt_id}", dependencies=[Depends(auth)])
def delete_debt(debt_id: int) -> dict:
    with db.tx() as c:
        ops.remove_debt(c, debt_id)
    return {"ok": True}


class Plan(BaseModel):
    extra_cents: int | None = None
    strategy: str | None = None


@app.post("/api/debts-plan", dependencies=[Depends(auth)])
def debt_plan(body: Plan) -> dict:
    with db.tx() as c:
        ops.set_debt_plan(c, body.extra_cents, body.strategy)
    return {"ok": True}


@app.get("/api/debts-simulate", dependencies=[Depends(auth)])
def simulate(extra_cents: int = 0, strategy: str = "avalanche") -> dict:
    """O controle deslizante pergunta aqui, sem gravar nada."""
    today = config.today()
    with db.tx() as c:
        debts = [dict(r) for r in c.execute("SELECT * FROM debts WHERE active = 1")]
    plan = finance.simulate_debts(debts, max(0, extra_cents), "snowball" if strategy == "snowball" else "avalanche")
    return {**plan, "free_month": add_months(month_of(today), plan["months"]) if plan["months"] else None}


class Budget(BaseModel):
    category: str
    limit_cents: int


@app.post("/api/budgets", dependencies=[Depends(auth)])
def set_budget(body: Budget) -> dict:
    with db.tx() as c:
        ops.set_category_budget(c, body.category, body.limit_cents)
    return {"ok": True}


class CategoryBody(BaseModel):
    label: str = Field(max_length=30)
    icon: str = Field(default="dot", max_length=20)


@app.post("/api/categories", dependencies=[Depends(auth)])
def create_category(body: CategoryBody) -> dict:
    with db.tx() as c:
        return {"key": ops.add_category(c, body.label, body.icon)}


@app.put("/api/categories/{key}", dependencies=[Depends(auth)])
def edit_category(key: str, body: CategoryBody) -> dict:
    with db.tx() as c:
        ops.update_category(c, key, body.label, body.icon)
    return {"ok": True}


@app.delete("/api/categories/{key}", dependencies=[Depends(auth)])
def delete_category(key: str) -> dict:
    with db.tx() as c:
        return {"moved": ops.remove_category(c, key)}


@app.get("/api/report", dependencies=[Depends(auth)])
def get_report(month: str = "") -> dict:
    today = config.today()
    if month and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "Mês inválido.")
    if month > month_of(today):
        month = month_of(today)
    with db.tx() as c:
        return finance.report(c, month or month_of(today), today)


class Goal(BaseModel):
    name: str = Field(max_length=80)
    target_cents: int
    due_month: str | None = None
    monthly_cents: int | None = None


@app.post("/api/goals", dependencies=[Depends(auth)])
def create_goal(body: Goal) -> dict:
    with db.tx() as c:
        return {"id": ops.add_goal(c, body.name, body.target_cents, body.due_month, body.monthly_cents)}


@app.put("/api/goals/{goal_id}", dependencies=[Depends(auth)])
def edit_goal(goal_id: int, body: Goal) -> dict:
    with db.tx() as c:
        ops.update_goal(c, goal_id, body.name, body.target_cents, body.due_month, body.monthly_cents)
    return {"ok": True}


@app.delete("/api/goals/{goal_id}", dependencies=[Depends(auth)])
def delete_goal(goal_id: int) -> dict:
    with db.tx() as c:
        ops.remove_goal(c, goal_id)
    return {"ok": True}


class Deposit(BaseModel):
    amount_cents: int


@app.post("/api/goals/{goal_id}/deposits", dependencies=[Depends(auth)])
def goal_deposit(goal_id: int, body: Deposit) -> dict:
    with db.tx() as c:
        return {"id": ops.deposit_goal(c, goal_id, body.amount_cents, config.today())}


@app.delete("/api/goal-deposits/{deposit_id}", dependencies=[Depends(auth)])
def delete_goal_deposit(deposit_id: int) -> dict:
    with db.tx() as c:
        c.execute("DELETE FROM goal_deposits WHERE id = ?", (deposit_id,))
    return {"ok": True}


class Settings(BaseModel):
    nudges_off: bool | None = None
    morning_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    evening_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@app.post("/api/settings", dependencies=[Depends(auth)])
def save_settings(body: Settings) -> dict:
    with db.tx() as c:
        if body.nudges_off is not None:
            db.set_setting(c, "nudges_off", "1" if body.nudges_off else "0")
        if body.morning_time:
            db.set_setting(c, "morning_time", body.morning_time)
        if body.evening_time:
            db.set_setting(c, "evening_time", body.evening_time)
    return {"ok": True}


# ---------- arquivos ----------


@app.post("/api/import", dependencies=[Depends(auth)])
async def import_file(file: UploadFile = File(...), card_id: int | None = Form(None)) -> dict:
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "Arquivo grande demais (limite de 15 MB).")
    today = config.today()
    name = file.filename or "arquivo"
    try:
        if name.lower().endswith(".pdf"):
            if not ai.enabled():
                raise HTTPException(422, "Ler PDF precisa da chave do DeepSeek. CSV e OFX funcionam sem ela.")
            items, kind = await ai.extract_document(raw, "application/pdf", today)
            is_card = kind == "card_invoice"
        else:
            items, is_card = importers.parse_file(name, raw)
    except importers.ImportFailed as exc:
        raise HTTPException(422, str(exc)) from exc
    with db.tx() as c:
        cards = c.execute("SELECT * FROM cards WHERE active = 1").fetchall()
        card = None
        if card_id:
            card = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        elif is_card and len(cards) == 1:
            card = cards[0]
        elif is_card and len(cards) > 1:
            return JSONResponse(
                {"needs_card": True, "count": len(items), "cards": [{"id": x["id"], "name": x["name"]} for x in cards]},
                status_code=409,
            )
        return importers.import_items(c, items, card, today)


@app.post("/api/import/{batch_id}/undo", dependencies=[Depends(auth)])
def undo_import(batch_id: str) -> dict:
    with db.tx() as c:
        return {"removed": importers.undo_batch(c, batch_id)}


@app.get("/api/export", dependencies=[Depends(auth)])
def export() -> Response:
    """Os dados são seus: tudo em JSON, a qualquer momento."""
    with db.tx() as c:
        tables = [
            "transactions",
            "recurring",
            "cards",
            "debts",
            "pauses",
            "category_budgets",
            "invoice_payments",
            "categories",
            "goals",
            "goal_deposits",
        ]
        payload = {t: [dict(r) for r in c.execute(f"SELECT * FROM {t}")] for t in tables}
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=1),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="forca-{config.today().isoformat()}.json"'},
    )


# ---------- PWA ----------


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
