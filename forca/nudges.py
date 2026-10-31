"""Avisos proativos. O teto diário existe porque app que incomoda é app desinstalado."""

from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

from . import ai, config, db, finance, ledger
from . import backup as backup_mod
from .bot import kb, today_message
from .finance import add_months, brl, month_of

log = logging.getLogger("forca.nudges")

MAX_SOFT_PER_DAY = 3
QUIET_START, QUIET_END = 22, 7
Send = Callable[[int, str, dict | None], Awaitable[None]]


def _sent(c: sqlite3.Connection, key: str) -> bool:
    return c.execute("SELECT 1 FROM nudge_log WHERE key = ?", (key,)).fetchone() is not None


def _mark(c: sqlite3.Connection, key: str, when: datetime) -> None:
    c.execute("INSERT OR IGNORE INTO nudge_log (key, sent_at) VALUES (?, ?)", (key, when.isoformat()))


def _soft_room(c: sqlite3.Connection, today: date) -> bool:
    count = c.execute(
        "SELECT COUNT(*) AS n FROM nudge_log WHERE key LIKE ?", (f"soft:{today.isoformat()}:%",)
    ).fetchone()["n"]
    return count < MAX_SOFT_PER_DAY


def _at(now: datetime, hhmm: str, grace_hours: int = 3) -> bool:
    """Passou da hora há pouco? A folga cobre reinício sem mandar "bom dia" de noite."""
    hour, minute = map(int, hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target <= now < target + timedelta(hours=grace_hours)


def collect(c: sqlite3.Connection, now: datetime) -> list[tuple[str, dict | None]]:
    """Decide o que enviar agora e já marca como enviado."""
    today = now.date()
    out: list[tuple[str, dict | None]] = []
    if db.get_setting(c, "nudges_off") == "1" or not QUIET_END <= now.hour < QUIET_START:
        return out
    day = today.isoformat()
    has_setup = c.execute("SELECT 1 FROM recurring WHERE kind = 'income' AND active = 1").fetchone() is not None
    t = finance.today_status(c, today)

    def once(key: str) -> bool:
        if _sent(c, key):
            return False
        _mark(c, key, now)
        return True

    def soft(name: str) -> bool:
        key = f"soft:{day}:{name}"
        if _sent(c, key) or not _soft_room(c, today):
            return False
        _mark(c, key, now)
        return True

    # Essenciais: manhã, vencendo hoje e lembrete de pausa não contam no teto.
    if has_setup and _at(now, db.get_setting(c, "morning_time", "08:00") or "08:00") and once(f"morning:{day}"):
        text, markup = today_message(c, today, skip_tomorrow=True)
        out.append((text, markup))

    # Um dia antes, às 9h: ainda dá tempo de separar o dinheiro e pagar.
    if _at(now, "09:00"):
        for item in finance.upcoming(c, today, 1):
            if item["days"] == 1 and once(f"duetomorrow:{item['due']}:{item['type']}:{item['id']}"):
                out.append(
                    (
                        f"⏰ <b>{html.escape(item['name'])}</b> vence amanhã: {brl(item['amount_cents'])}.",
                        kb([("Já paguei", f"paid:{item['type']}:{item['id']}:{item['month']}")]),
                    )
                )

    if _at(now, "18:00", 2):
        for item in finance.upcoming(c, today, 0):
            if item["days"] == 0 and once(f"duetoday:{day}:{item['type']}:{item['id']}"):
                out.append(
                    (
                        f"<b>{html.escape(item['name'])}</b> vence hoje: {brl(item['amount_cents'])}. Já pagou?",
                        kb([("Paguei", f"paid:{item['type']}:{item['id']}:{item['month']}")]),
                    )
                )

    for pause in c.execute("SELECT * FROM pauses WHERE status = 'waiting' AND reminded = 0").fetchall():
        if datetime.fromisoformat(pause["remind_at"]) <= now:
            c.execute("UPDATE pauses SET reminded = 1 WHERE id = ?", (pause["id"],))
            out.append(
                (
                    f"Passaram 24 horas. Você ainda quer <b>{html.escape(pause['item'])}</b> por {brl(pause['amount_cents'])}?",
                    kb([("Desisti", f"pzno:{pause['id']}"), ("Comprei", f"pzbuy:{pause['id']}")]),
                )
            )

    # Opcionais, em ordem de utilidade, até o teto do dia.
    if not c.execute("SELECT 1 FROM transactions LIMIT 1").fetchone():
        return out  # sem dados não há o que comentar

    for card in finance.cards_overview(c, today):
        if card["days_to_closing"] == 2 and _at(now, "10:00") and soft(f"closing:{card['id']}"):
            out.append(
                (
                    f"<b>{html.escape(card['name'])}</b> fecha em 2 dias, com {brl(card['current_invoice_cents'])} na fatura. "
                    f"O que comprar depois disso só vence no mês seguinte, mas continua pesando no orçamento de agora.",
                    None,
                )
            )

    if has_setup and today.day >= 5 and t.status not in ("broken", "setup") and _at(now, "12:30"):
        over = finance.projected_month_end(c, today)
        week = today.isocalendar()[1]
        if t.budget.available > 0 and over > t.budget.available * 0.1 and not _sent(c, f"pace:{week}") and soft("pace"):
            _mark(c, f"pace:{week}", now)
            out.append(
                (
                    f"Neste ritmo, o mês fecha <b>{brl(over)}</b> acima do que cabe. Para fechar no azul, o limite é {brl(t.tomorrow)} por dia até o fim do mês.",
                    None,
                )
            )

    if today.day >= 6 and _at(now, "10:30") and not _sent(c, f"goalask:{month_of(today)}"):
        pending = [g for g in finance.goals_overview(c, today) if g["due_this_month_cents"] > 0]
        if pending and soft("goal"):
            _mark(c, f"goalask:{month_of(today)}", now)
            g = pending[0]
            out.append(
                (
                    f"Este mês falta guardar {brl(g['due_this_month_cents'])} em <b>{html.escape(g['name'])}</b>. Se já guardou, me diga: <code>guardei {g['due_this_month_cents'] // 100} na {html.escape(g['name'].lower())}</code>.",
                    None,
                )
            )

    if _at(now, "17:30"):
        risky = finance.risky_weekday(c, today)
        if risky and soft("pattern"):
            weekday = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][today.weekday()]
            out.append(
                (
                    f"Toda {weekday} costuma ter {brl(risky['average_cents'])} em {db.category_label(risky['category'])}. "
                    f"Hoje ainda cabe {brl(max(0, t.left_today))}. Só para decidir antes, não depois.",
                    None,
                )
            )

    if _at(now, db.get_setting(c, "evening_time", "20:30") or "20:30"):
        logged = c.execute(
            "SELECT 1 FROM transactions WHERE date = ? AND source != 'opening' LIMIT 1", (day,)
        ).fetchone()
        zero = c.execute("SELECT 1 FROM zero_days WHERE date = ?", (day,)).fetchone()
        if not logged and not zero and soft("evening"):
            streak = finance.streak(c, today)
            suffix = f" Sua sequência é de {streak} dias." if streak >= 3 else ""
            out.append(
                (
                    f"Hoje não vi nenhum gasto. Foi zero mesmo, ou faltou registrar?{suffix}",
                    kb([("Foi zero", "zero:today")]),
                )
            )
    return out


def weekly_facts(c: sqlite3.Connection, today: date) -> str:
    start = today - timedelta(days=6)
    previous = start - timedelta(days=7)
    variable = "kind = 'expense' AND committed = 0 AND recurring_id IS NULL AND debt_id IS NULL"
    this_week = c.execute(
        f"SELECT COALESCE(SUM(amount_cents),0) AS t FROM transactions WHERE {variable} AND date BETWEEN ? AND ?",
        (start.isoformat(), today.isoformat()),
    ).fetchone()["t"]
    last_week = c.execute(
        f"SELECT COALESCE(SUM(amount_cents),0) AS t FROM transactions WHERE {variable} AND date BETWEEN ? AND ?",
        (previous.isoformat(), (start - timedelta(days=1)).isoformat()),
    ).fetchone()["t"]
    top = c.execute(
        f"SELECT category, SUM(amount_cents) AS t FROM transactions WHERE {variable} AND date BETWEEN ? AND ? GROUP BY category ORDER BY t DESC LIMIT 3",
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    t = finance.today_status(c, today)
    debts = finance.debts_overview(c, today)
    lines = [
        "<b>Sua semana</b>",
        f"Gastou {brl(this_week)}" + (f" (na anterior, {brl(last_week)})" if last_week else "") + ".",
    ]
    if top:
        lines.append(
            "Mais pesado: " + ", ".join(f"{db.category_label(r['category'])} {brl(r['t'])}" for r in top) + "."
        )
    lines.append(f"Restam {brl(t.budget.remaining)} para {t.days_left} dias: {brl(t.tomorrow)} por dia.")
    if debts["debts"]:
        when = f"livre em {finance.month_name(debts['free_month'])}" if debts["free_month"] else "plano atual não quita"
        lines.append(f"Dívidas: {brl(debts['total_cents'])}, {when}.")
    saved = finance.saved_by_pauses(c)
    if saved:
        lines.append(f"Compras que você deixou passar: {brl(saved)}.")
    goals = finance.goals_overview(c, today)
    if goals:
        lines.append(
            "Metas: "
            + ", ".join(f"{g['name']} {brl(g['saved_cents'])} de {brl(g['target_cents'])}" for g in goals[:3])
            + "."
        )
    streak = finance.streak(c, today)
    if streak >= 2:
        lines.append(f"Registro em dia há {streak} dias.")
    return "\n".join(lines)


def monthly_close(c: sqlite3.Connection, today: date) -> str:
    """No dia 1º: fecha o mês anterior e aplica um mês de juros nas dívidas."""
    previous = add_months(month_of(today), -1)
    b = finance.month_budget(c, previous)
    interest = ledger.accrue_debt_interest(c, today)
    lines = [f"<b>{finance.month_name(previous).capitalize()} fechou.</b>"]
    if b.remaining >= 0:
        lines.append(f"Sobraram {brl(b.remaining)} dos {brl(b.available)} para viver.")
    else:
        lines.append(
            f"Passou {brl(-b.remaining)}. Esse valor já foi descontado deste mês, para o número do dia continuar verdadeiro."
        )
    if interest:
        lines.append(f"Juros somados às dívidas neste mês: {brl(interest)}. Se o saldo real for outro, me diga.")
    return "\n".join(lines)


async def tick(send: Send, chat: int | None, now: datetime | None = None) -> None:
    now = now or config.now()
    today = now.date()
    messages: list[tuple[str, dict | None]] = []
    weekly: str | None = None
    with db.tx() as c:
        # Juros e fechamento rodam mesmo sem Telegram: o saldo não pode depender do bot.
        if (
            today.day == 1
            and db.get_setting(c, "started_month")
            and db.get_setting(c, "started_month") < month_of(today)
        ):
            if not _sent(c, f"close:{month_of(today)}"):
                _mark(c, f"close:{month_of(today)}", now)
                closing = monthly_close(c, today)
                started = db.get_setting(c, "started_date")
                # Começou há poucos dias: não há mês para resumir.
                if not started or (today - date.fromisoformat(started)).days >= 7:
                    messages.append((closing, None))
        if chat is not None:
            messages += collect(c, now)
            if (
                today.weekday() == 6
                and _at(now, "19:00")
                and db.get_setting(c, "nudges_off") != "1"
                and c.execute("SELECT 1 FROM transactions LIMIT 1").fetchone()
                and not _sent(c, f"weekly:{today.isoformat()}")
            ):
                _mark(c, f"weekly:{today.isoformat()}", now)
                weekly = weekly_facts(c, today)
    if weekly:
        note = await ai.write_note(weekly)
        messages.append((f"{weekly}\n\n{html.escape(note)}" if note else weekly, None))
    if chat is not None:
        for text, markup in messages:
            await send(chat, text, markup)


def backup(now: datetime) -> None:
    """Uma cópia por dia, guardadas por 14 dias. É sua vida financeira inteira nesse arquivo."""
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = config.BACKUP_DIR / f"forca-{now.date().isoformat()}.db"
    if target.exists():
        return
    source = db.connect()
    dest = sqlite3.connect(target)
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()
    for old in sorted(config.BACKUP_DIR.glob("forca-*.db"))[:-14]:
        old.unlink()


OFFSITE_EVERY_DAYS = 7
OFFSITE_MAX_BYTES = 45 * 1024 * 1024
OFFSITE_CAPTION = "Backup semanal da Força, criptografado. Abre só com a senha do app. Pode deixar aqui no chat."
_offsite_retry_at: datetime | None = None


async def offsite_backup(send_document: Callable, chat: int | None, now: datetime) -> bool:
    """Toda semana, uma cópia sai da VPS pelo próprio Telegram. Se falhar, tenta de novo em 1 hora."""
    global _offsite_retry_at
    if chat is None or not config.PASSWORD or (_offsite_retry_at and now < _offsite_retry_at):
        return False
    with db.tx() as c:
        last = db.get_setting(c, "offsite_backup_at")
    if last and (now - datetime.fromisoformat(last)).days < OFFSITE_EVERY_DAYS:
        return False
    try:
        blob = await asyncio.to_thread(lambda: backup_mod.encrypt(backup_mod.snapshot(), config.PASSWORD))
        if len(blob) > OFFSITE_MAX_BYTES:
            raise RuntimeError(f"Backup grande demais para o Telegram: {len(blob)} bytes")
        await send_document(chat, f"forca-{now.date().isoformat()}.forca", blob, OFFSITE_CAPTION)
    except Exception as exc:
        log.warning("Backup externo falhou: %s", type(exc).__name__)
        _offsite_retry_at = now + timedelta(hours=1)
        return False
    _offsite_retry_at = None
    with db.tx() as c:
        db.set_setting(c, "offsite_backup_at", now.isoformat())
    return True


async def run(send: Send, send_document: Callable | None = None) -> None:
    while True:
        try:
            now = config.now()
            with db.tx() as c:
                owner = db.get_setting(c, "owner_chat_id")
            await tick(send, int(owner) if owner else None, now)
            if now.hour >= 3:
                await asyncio.to_thread(backup, now)
            if send_document is not None:
                await offsite_backup(send_document, int(owner) if owner else None, now)
        except Exception:
            log.exception("Falha no ciclo de avisos")
        await asyncio.sleep(60)
