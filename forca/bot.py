"""Bot do Telegram por long polling: não precisa de porta aberta nem de domínio."""

from __future__ import annotations

import asyncio
import html
import logging
import secrets
from datetime import date
from typing import Any

import httpx

from . import ai, config, db, finance, importers, ledger, onboarding, ops, parser, transcribe
from .finance import brl, month_of

log = logging.getLogger("forca.bot")

BUTTONS = [["Hoje", "Pagar", "Metas"]]
_NAMES = {"bill": "conta", "invoice": "fatura", "debt": "dívida"}
MAX_FILE = 15 * 1024 * 1024


KEYBOARD = {"keyboard": [[{"text": t} for t in row] for row in BUTTONS], "resize_keyboard": True}


def kb(*rows: list[tuple[str, str]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class Telegram:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"
        self.http = client or httpx.AsyncClient(timeout=70)

    async def api(self, method: str, **params: Any) -> Any:
        response = await self.http.post(f"{self.base}/{method}", json=params)
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {data.get('description')}")
        return data["result"]

    async def send(self, chat_id: int, text: str, markup: dict | None = None) -> None:
        params: dict = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if markup:
            params["reply_markup"] = markup
        try:
            await self.api("sendMessage", **params)
        except RuntimeError as exc:
            if "parse entities" not in str(exc):
                raise
            # O agente pode gerar HTML que o Telegram recusa: nunca perder a resposta por isso.
            params.pop("parse_mode")
            await self.api("sendMessage", **params)

    async def send_document(self, chat_id: int, filename: str, data: bytes, caption: str) -> None:
        response = await self.http.post(
            f"{self.base}/sendDocument",
            data={"chat_id": str(chat_id), "caption": caption, "disable_notification": "true"},
            files={"document": (filename, data, "application/octet-stream")},
        )
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram sendDocument: {result.get('description')}")

    async def download(self, file_id: str) -> bytes | None:
        info = await self.api("getFile", file_id=file_id)
        if info.get("file_size", 0) > MAX_FILE:
            return None
        response = await self.http.get(f"{self.file_base}/{info['file_path']}")
        if response.status_code != 200:  # sem raise_for_status: a mensagem dele traz a URL com o token
            raise RuntimeError(f"Telegram getFile: HTTP {response.status_code}")
        return response.content


class Bot:
    def __init__(self, telegram: Telegram):
        self.tg = telegram
        # Decisões que aguardam um toque: se o processo reiniciar, a pessoa manda de novo.
        self.pending: dict[str, dict] = {}

    # ---------- entrada ----------

    async def run(self) -> None:
        with db.tx() as c:
            offset = int(db.get_setting(c, "telegram_offset", "0") or 0)
        while True:
            try:
                updates = await self.tg.api(
                    "getUpdates", offset=offset, timeout=50, allowed_updates=["message", "callback_query"]
                )
            except (httpx.HTTPError, RuntimeError, ValueError):
                log.warning("Falha no getUpdates; tentando de novo", exc_info=True)
                await asyncio.sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                # Grava antes de tratar: uma mensagem que derruba o bot não pode ficar em loop.
                with db.tx() as c:
                    db.set_setting(c, "telegram_offset", str(offset))
                try:
                    await self.handle(update)
                except Exception:
                    log.exception("Erro ao tratar mensagem")
                    chat = _chat_of(update)
                    if chat and self._is_owner(chat):
                        await self._safe_send(chat, "Algo deu errado aqui e não registrei isso. Pode mandar de novo?")

    async def _safe_send(self, chat: int, text: str) -> None:
        try:
            await self.tg.send(chat, text)
        except (httpx.HTTPError, RuntimeError):
            log.warning("Não consegui enviar", exc_info=True)

    def _is_owner(self, chat: int) -> bool:
        with db.tx() as c:
            return db.get_setting(c, "owner_chat_id") == str(chat)

    async def handle(self, update: dict) -> None:
        chat = _chat_of(update)
        if chat is None:
            return
        if "message" in update and await self._maybe_pair(chat, update["message"]):
            return
        if not self._is_owner(chat):
            return  # silêncio total para estranhos: o bot nem confirma que existe
        if "callback_query" in update:
            await self.on_callback(chat, update["callback_query"])
            return
        message = update["message"]
        if "text" in message:
            await self.on_text(chat, message["text"])
        elif "voice" in message or "audio" in message:
            await self.on_voice(chat, message.get("voice") or message["audio"])
        elif "photo" in message:
            await self.on_file(chat, message["photo"][-1]["file_id"], "foto.jpg", "image/jpeg")
        elif "document" in message:
            d = message["document"]
            await self.on_file(chat, d["file_id"], d.get("file_name", "arquivo"), d.get("mime_type", ""))

    async def _maybe_pair(self, chat: int, message: dict) -> bool:
        text = (message.get("text") or "").strip()
        if not text.startswith("/start"):
            return False
        with db.tx() as c:
            owner = db.get_setting(c, "owner_chat_id")
        if owner:
            return False
        parts = text.split()
        if config.PAIR_CODE and len(parts) == 2 and secrets.compare_digest(parts[1], config.PAIR_CODE):
            with db.tx() as c:
                db.set_setting(c, "owner_chat_id", str(chat))
            await self.tg.send(chat, WELCOME, KEYBOARD)
            await self.start_onboarding(chat)
        return True

    # ---------- texto ----------

    async def on_text(self, chat: int, text: str) -> None:
        today = config.today()
        text = text.strip()
        low = parser.normalize(text)
        commands = {
            "/start": self.send_home,
            "/hoje": self.send_today,
            "hoje": self.send_today,
            "/mes": self.send_month,
            "mes": self.send_month,
            "/pagar": self.send_bills,
            "pagar": self.send_bills,
            "/contas": self.send_bills,
            "contas": self.send_bills,
            "/fatura": self.send_bills,
            "/comecar": self.start_onboarding,
            "/cadastro": self.start_onboarding,
            "/cancelar": self.stop_onboarding,
            "cancelar": self.stop_onboarding,
            "/dividas": self.send_debts,
            "dividas": self.send_debts,
            "/metas": self.send_goals,
            "metas": self.send_goals,
            "/relatorio": self.send_report,
            "relatorio": self.send_report,
            "/limites": self.send_limits,
            "limites": self.send_limits,
            "/categorias": self.send_categories,
            "categorias": self.send_categories,
            "/ajuda": self.send_help,
            "ajuda": self.send_help,
            "/desfazer": self.undo_last,
            "desfazer": self.undo_last,
            "/app": self.send_app,
            "/silencio": self.toggle_mute,
        }
        handler = commands.get(low.split("@")[0])
        if handler:
            await handler(chat)
            return

        with db.tx() as c:
            in_setup = onboarding.active(c)
        if in_setup:
            await self.continue_onboarding(chat, text)
            return

        question = parser.parse_purchase_question(text)
        if question:
            await self.send_assessment(chat, *question)
            return

        with db.tx() as c:
            captured = ops.capture(c, text, today, "telegram")
            if captured and captured["type"] == "check":
                reply, markup = self._check_reply(captured, text)
            elif captured:
                reply, markup = self._log_reply(c, captured, today)
        if captured:
            await self.tg.send(chat, reply, markup)
            return

        paid = self._paid_without_amount(low, today)
        if paid:
            await self.tg.send(chat, paid)
            return

        if not ai.enabled():
            await self.tg.send(
                chat,
                "Não entendi. Tente algo como <code>mercado 87</code> ou /ajuda.\n\nConversar livremente exige a chave do DeepSeek configurada.",
            )
            return
        await self.tg.api("sendChatAction", chat_id=chat, action="typing")
        await self.tg.send(chat, await ai.chat(text, today))

    # ---------- cadastro por conversa ----------

    async def _send_step(self, chat: int, reply: onboarding.Reply) -> None:
        if reply.finished:
            await self.tg.send(chat, reply.text, KEYBOARD)
            await self.send_today(chat)
            return
        rows = [
            [(label, f"ob:{value}") for label, value in reply.options[i : i + 3]]
            for i in range(0, len(reply.options), 3)
        ]
        await self.tg.send(chat, reply.text, kb(*rows) if rows else None)

    async def start_onboarding(self, chat: int) -> None:
        with db.tx() as c:
            reply = onboarding.start(c, config.today())
        await self._send_step(chat, reply)

    async def continue_onboarding(self, chat: int, text: str) -> None:
        with db.tx() as c:
            try:
                reply = onboarding.answer(c, text, config.today())
            except ops.Invalid as exc:
                reply = onboarding.Reply(html.escape(str(exc)))
        await self._send_step(chat, reply)

    async def stop_onboarding(self, chat: int) -> None:
        with db.tx() as c:
            onboarding.cancel(c)
        await self.tg.send(
            chat,
            "Parei por aqui; o que você já respondeu ficou salvo. Para continuar depois, mande /comecar.",
            KEYBOARD,
        )

    def _check_reply(self, r: dict, text: str) -> tuple[str, dict]:
        token = secrets.token_hex(4)
        self.pending[token] = {"text": text}
        return (
            f"Só para conferir: <b>{brl(r['amount_cents'])}</b> em {html.escape(r['description'])}. É isso mesmo? Ainda não registrei.",
            kb([("Sim, registrar", f"chk:{token}"), ("Não, errei", f"chkno:{token}")]),
        )

    def _paid_without_amount(self, low: str, today: date) -> str | None:
        """ "paguei o aluguel" sem valor marca pelo valor previsto."""
        if not low.startswith(("paguei", "pago")):
            return None
        target = ledger.match_words(low) - {"paguei", "pago"}
        with db.tx() as c:
            for item in finance.upcoming(c, today, 35):
                if ledger.match_words(item["name"]) & target:
                    name = ledger.mark_paid(c, item["type"], item["id"], item["month"], today)
                    return f"✓ {html.escape(name)} marcada como paga: {brl(item['amount_cents'])}."
        return None

    def _log_reply(self, c: Any, r: dict, today: date) -> tuple[str, dict | None]:
        if r["type"] == "zero":
            return f"Dia sem gasto registrado. Sequência: {finance.streak(c, today)} dias.", None
        if r["type"] == "goal":
            return html.escape(ops.goal_text(r)), kb([("Desfazer", f"ugoal:{r['deposit_id']}")])
        if r["type"] == "recurring":
            label = "Renda" if r["kind"] == "income" else "Conta fixa"
            return (
                f"✓ {label}: {html.escape(r['description'])}, {brl(r['amount_cents'])} todo dia {r['day']}.\n{ops.feedback(c, today, today)}",
                None,
            )
        description = html.escape(r["description"])
        tx = r["ids"][0]
        amount = brl(r["amount_cents"])
        if r["type"] == "income":
            return f"✓ Entrou {amount}: {description}\n{ops.feedback(c, today, r['date'])}", kb(
                [("Desfazer", f"undo:{tx}")]
            )

        if r.get("linked") == "bill":
            head = f"✓ {html.escape(r['linked_name'])} paga: {amount}"
        elif r.get("linked") == "debt":
            row = c.execute(
                "SELECT balance_cents FROM debts WHERE id = (SELECT debt_id FROM transactions WHERE id = ?)", (tx,)
            ).fetchone()
            head = f"✓ {html.escape(r['linked_name'])}: {amount}. Saldo agora: {brl(row['balance_cents'])}"
        else:
            head = f"✓ {description} {amount} · {db.category_label(r['category'])}"
            if r.get("installments", 1) > 1:
                head += f" · {r['installments']}x"
            if r.get("card"):
                head += f" · {html.escape(r['card'])}"
        lines = [head, ops.feedback(c, today, r["date"])]
        alert = ops.category_alert(c, r["category"], today)
        if alert:
            lines.append(alert)
        rows = [[("Desfazer", f"undo:{tx}"), ("Categoria", f"cat:{tx}")]]
        if r.get("needs_card"):
            lines.append("Em qual cartão?")
            rows.insert(
                0,
                [
                    (card["name"], f"setcard:{tx}:{card['id']}")
                    for card in c.execute("SELECT * FROM cards WHERE active = 1")
                ],
            )
        return "\n".join(lines), kb(*rows)

    # ---------- telas ----------

    async def send_home(self, chat: int) -> None:
        await self.tg.send(
            chat,
            "Tudo certo por aqui.",
            {"keyboard": [[{"text": t} for t in row] for row in BUTTONS], "resize_keyboard": True},
        )
        await self.send_today(chat)

    async def send_today(self, chat: int) -> None:
        with db.tx() as c:
            text, markup = today_message(c, config.today())
        await self.tg.send(chat, text, markup)

    async def send_month(self, chat: int) -> None:
        today = config.today()
        with db.tx() as c:
            b = finance.month_budget(c, month_of(today))
            cats = finance.categories_for(c, month_of(today))[:6]
        lines = [
            f"<b>{finance.month_name(month_of(today))}</b>",
            "",
            f"Entra  {brl(b.income)}",
            f"Contas fixas  {brl(b.fixed)}",
            f"Dívidas  {brl(b.debts)}",
            f"Metas  {brl(b.goals)}",
            f"Parcelas antigas  {brl(b.committed)}",
        ]
        if b.carry:
            lines.append(f"Estouro do mês passado  {brl(b.carry)}")
        lines += [
            "",
            f"Para viver  <b>{brl(b.available)}</b>",
            f"Já gastou  {brl(b.spent)}",
            f"Resta  <b>{brl(b.remaining)}</b>",
        ]
        if cats:
            lines += [""] + [
                f"{db.category_label(r['category']).capitalize()}  {brl(r['spent_cents'])}"
                + (f" de {brl(r['limit_cents'])}" if r["limit_cents"] else "")
                for r in cats
                if r["spent_cents"]
            ]
        await self.tg.send(chat, "\n".join(lines))

    async def send_bills(self, chat: int) -> None:
        today = config.today()
        with db.tx() as c:
            items = finance.upcoming(c, today, 30)
            cards = finance.cards_overview(c, today)
        if not items and not cards:
            await self.tg.send(chat, "Nada a vencer nos próximos 30 dias.")
            return
        lines, buttons = ["<b>Próximos 30 dias</b>"], []
        for i in items[:12]:
            lines.append(f"{when_label(i['days'], i['due'])}  {html.escape(i['name'])}  {brl(i['amount_cents'])}")
            if len(buttons) < 5:
                buttons.append([(f"Paguei {i['name']}"[:40], f"paid:{i['type']}:{i['id']}:{i['month']}")])
        for card in cards:
            lines.append(
                f"\n<b>{html.escape(card['name'])}</b>: fatura aberta em {brl(card['current_invoice_cents'])}, fecha em {card['days_to_closing']} dias."
            )
            if card["future_committed_cents"]:
                lines.append(f"Já comprometido nas próximas: {brl(card['future_committed_cents'])}.")
        await self.tg.send(chat, "\n".join(lines), kb(*buttons) if buttons else None)

    async def send_debts(self, chat: int) -> None:
        with db.tx() as c:
            d = finance.debts_overview(c, config.today())
        if not d["debts"]:
            await self.tg.send(
                chat,
                'Nenhuma dívida cadastrada. Se houver, me conte: "devo 3000 no cartão a 14% ao mês, mínimo 300, vence dia 10".',
            )
            return
        lines = [f"<b>Você deve {brl(d['total_cents'])}</b>", f"Juros: {brl(d['monthly_interest_cents'])} por mês", ""]
        for index, debt in enumerate(d["debts"]):
            mark = "→ " if index == 0 else ""
            late = " · atrasada" if debt["overdue"] else ""
            rate = f"{debt['monthly_rate']:g}".replace(".", ",")
            lines.append(f"{mark}{html.escape(debt['name'])}  {brl(debt['balance_cents'])} · {rate}% a.m.{late}")
        lines.append("")
        if d["plan"]["feasible"]:
            lines.append(
                f"No plano atual, você fica livre em <b>{finance.month_name(d['free_month'])}</b>, pagando {brl(d['plan']['total_interest_cents'])} de juros."
            )
        else:
            lines.append(
                "<b>No valor atual, essas dívidas não acabam nunca:</b> os juros crescem mais do que você paga. Renegociar vem antes de tudo."
            )
        await self.tg.send(chat, "\n".join(lines))

    async def send_goals(self, chat: int) -> None:
        with db.tx() as c:
            goals = finance.goals_overview(c, config.today())
        if not goals:
            await self.tg.send(
                chat,
                "Nenhuma meta ainda. Me diga, por exemplo: <i>quero juntar 5000 de reserva até junho, guardando 500 por mês</i>.",
            )
            return
        lines = ["<b>Suas metas</b>"]
        for g in goals:
            line = f"\n<b>{html.escape(g['name'])}</b>: {brl(g['saved_cents'])} de {brl(g['target_cents'])}"
            if g["done"]:
                line += " · concluída"
            elif g["finish_month"]:
                line += f"\nNo ritmo de {brl(g['monthly_cents'])} por mês, termina em {finance.month_name(g['finish_month'])}."
            lines.append(line)
        lines.append("\nPara registrar: <code>guardei 200 na reserva</code>")
        await self.tg.send(chat, "\n".join(lines))

    async def send_report(self, chat: int) -> None:
        today = config.today()
        with db.tx() as c:
            r = finance.report(c, month_of(today), today)
        lines = [
            f"<b>Relatório de {finance.month_name(r['month'])}</b>",
            f"Gastou {brl(r['spent_cents'])}, média de {brl(r['daily_average_cents'])} por dia.",
        ]
        lines += [html.escape(i["text"]) for i in r["insights"]]
        rows = [x for x in r["categories"] if x["spent_cents"]][:5]
        if rows:
            lines += ["", "<b>Onde foi</b>"] + [f"{html.escape(x['label'])}  {brl(x['spent_cents'])}" for x in rows]
        if r["top_expenses"]:
            lines += ["", "<b>Maiores gastos</b>"] + [
                f"{html.escape(x['description'])}  {brl(x['amount_cents'])}" for x in r["top_expenses"][:3]
            ]
        lines += ["", f"Relatório completo no app: {config.BASE_URL}"]
        await self.tg.send(chat, "\n".join(lines))

    async def send_limits(self, chat: int) -> None:
        today = config.today()
        with db.tx() as c:
            rows = [r for r in finance.categories_for(c, month_of(today)) if r["limit_cents"]]
        if not rows:
            await self.tg.send(
                chat,
                "Nenhum limite definido. Me diga, por exemplo: <i>limite de 800 no mercado</i>, ou defina na aba Mês do app.",
            )
            return
        lines = ["<b>Seus limites</b>"] + [
            f"{html.escape(r['label'])}: {brl(r['spent_cents'])} de {brl(r['limit_cents'])}" for r in rows
        ]
        await self.tg.send(chat, "\n".join(lines))

    async def send_categories(self, chat: int) -> None:
        with db.tx() as c:
            rows = [r for r in finance.category_list(c) if r["key"] not in parser.SYSTEM_CATEGORIES]
        text = "<b>Categorias</b>\n" + "\n".join(html.escape(r["label"]) for r in rows)
        await self.tg.send(chat, text + "\n\nPara criar outra, me diga: <i>cria a categoria Pilates</i>.")

    async def send_help(self, chat: int) -> None:
        await self.tg.send(chat, HELP)

    async def send_app(self, chat: int) -> None:
        await self.tg.send(chat, f"Seu painel: {config.BASE_URL}")

    async def toggle_mute(self, chat: int) -> None:
        with db.tx() as c:
            muted = db.get_setting(c, "nudges_off") == "1"
            db.set_setting(c, "nudges_off", "0" if muted else "1")
        await self.tg.send(
            chat,
            "Avisos ligados de novo."
            if muted
            else "Avisos pausados. Só falo quando você falar comigo. /silencio liga de novo.",
        )

    async def undo_last(self, chat: int) -> None:
        with db.tx() as c:
            last = ledger.last_transaction(c)
            removed = ledger.delete_transaction(c, last["id"]) if last else []
        if removed:
            await self.tg.send(chat, f"Desfeito: {html.escape(removed[0]['description'])}.")
        else:
            await self.tg.send(chat, "Não há nada para desfazer.")

    # ---------- freio ----------

    async def send_assessment(self, chat: int, item: str, amount: int, installments: int) -> None:
        with db.tx() as c:
            a = finance.assess_purchase(c, config.today(), amount, installments)
        token = secrets.token_hex(4)
        self.pending[token] = {"item": item, "amount": amount, "installments": installments}
        rows = [[("Esperar 24h", f"p24:{token}"), ("Desisti", f"pno:{token}")], [("Comprei", f"pbuy:{token}")]]
        await self.tg.send(chat, ops.assessment_text(html.escape(item), a), kb(*rows))

    # ---------- áudio e arquivos ----------

    async def on_voice(self, chat: int, media: dict) -> None:
        await self.tg.api("sendChatAction", chat_id=chat, action="typing")
        raw = await self.tg.download(media["file_id"])
        text = await transcribe.transcribe(raw) if raw else None
        if not text:
            await self.tg.send(chat, "Não consegui entender o áudio. Pode mandar por texto?")
            return
        await self.tg.send(chat, f"<i>{html.escape(text)}</i>")
        await self.on_text(chat, text)

    async def on_file(self, chat: int, file_id: str, filename: str, mime: str) -> None:
        raw = await self.tg.download(file_id)
        if raw is None:
            await self.tg.send(chat, "Arquivo grande demais (limite de 15 MB).")
            return
        lower = filename.lower()
        try:
            if mime == "application/pdf" or lower.endswith(".pdf") or mime.startswith("image/"):
                if not ai.enabled():
                    await self.tg.send(
                        chat, "Ler PDF e foto precisa da chave do DeepSeek. CSV e OFX funcionam sem ela."
                    )
                    return
                await self.tg.api("sendChatAction", chat_id=chat, action="typing")
                media = "application/pdf" if lower.endswith(".pdf") or mime == "application/pdf" else mime
                items, kind = await ai.extract_document(raw, media)
                is_card = kind == "card_invoice"
            else:
                items, is_card = importers.parse_file(filename, raw)
                kind = "card_invoice" if is_card else "bank_statement"
        except importers.ImportFailed as exc:
            await self.tg.send(chat, html.escape(str(exc)))
            return
        if not items:
            await self.tg.send(chat, "Não encontrei lançamentos aí.")
            return

        with db.tx() as c:
            cards = c.execute("SELECT * FROM cards WHERE active = 1").fetchall()
        if is_card and len(cards) > 1:
            token = secrets.token_hex(4)
            self.pending[token] = {"items": items}
            rows = [[(card["name"], f"imp:{token}:{card['id']}")] for card in cards]
            await self.tg.send(chat, f"Encontrei {len(items)} lançamentos de fatura. De qual cartão?", kb(*rows))
            return
        await self._import(chat, items, cards[0]["id"] if is_card and cards else None, is_card and not cards)

    async def _import(self, chat: int, items: list[importers.Item], card_id: int | None, no_card: bool = False) -> None:
        today = config.today()
        with db.tx() as c:
            card = c.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone() if card_id else None
            s = importers.import_items(c, items, card, today)
        lines = [f"<b>{s['added']} novos</b> · {brl(s['total_cents'])}"]
        if s["matched"]:
            lines.append(f"{s['matched']} você já tinha registrado, não dupliquei.")
        if s["already"]:
            lines.append(f"{s['already']} já estavam importados.")
        if s["ignored"]:
            lines.append(f"{s['ignored']} ignorados (pagamento de fatura, aplicações).")
        if s["uncategorized"]:
            lines.append(f"{s['uncategorized']} sem categoria: dá para ajustar no app.")
        if no_card:
            lines.append("Parece fatura, mas não há cartão cadastrado: lancei como gastos comuns.")
        await self.tg.send(
            chat, "\n".join(lines), kb([("Desfazer importação", f"undob:{s['batch_id']}")]) if s["added"] else None
        )

    # ---------- botões ----------

    async def on_callback(self, chat: int, query: dict) -> None:
        data = query.get("data", "")
        await self.tg.api("answerCallbackQuery", callback_query_id=query["id"])
        message_id = query["message"]["message_id"]
        parts = data.split(":")
        action = parts[0]
        today = config.today()

        async def done(text: str, markup: dict | None = None) -> None:
            params: dict = {"chat_id": chat, "message_id": message_id, "text": text, "parse_mode": "HTML"}
            if markup:
                params["reply_markup"] = markup
            await self.tg.api("editMessageText", **params)

        if action == "undo":
            with db.tx() as c:
                removed = ledger.delete_transaction(c, int(parts[1]))
                note = ops.feedback(c, today, today) if removed else ""
            await done(f"Desfeito. {note}" if removed else "Esse lançamento já não existe.")
        elif action == "undob":
            with db.tx() as c:
                count = importers.undo_batch(c, parts[1])
            await done(f"Importação desfeita: {count} lançamentos removidos.")
        elif action == "cat":
            with db.tx() as c:
                names = [r["key"] for r in finance.category_list(c) if r["key"] not in ("renda", "dividas")]
            rows = [
                [(db.category_label(n).capitalize(), f"setcat:{parts[1]}:{n}") for n in names[i : i + 3]]
                for i in range(0, len(names), 3)
            ]
            await done("Qual categoria?", kb(*rows))
        elif action == "setcat":
            with db.tx() as c:
                ledger.set_category(c, int(parts[1]), parts[2])
            await done(f"Categoria: {db.category_label(parts[2])}. Da próxima vez eu já sei.")
        elif action == "setcard":
            with db.tx() as c:
                ledger.assign_card(c, int(parts[1]), int(parts[2]))
                card = c.execute("SELECT name FROM cards WHERE id = ?", (int(parts[2]),)).fetchone()
            await done(f"Lançado no {html.escape(card['name'])}." if card else "Cartão não encontrado.")
        elif action == "paid":
            with db.tx() as c:
                name = ledger.mark_paid(c, parts[1], int(parts[2]), parts[3], today)
                note = ops.feedback(c, today, today)
            await self.tg.send(chat, f"✓ {html.escape(name or 'Pago')}. {note}")
        elif action == "zero":
            with db.tx() as c:
                ledger.zero_day(c, today)
                streak = finance.streak(c, today)
            await done(f"Dia sem gasto. Sequência: {streak} dias.")
        elif action in ("p24", "pno", "pbuy"):
            await self._purchase_choice(action, parts[1], done, today)
        elif action in ("pz", "pzno", "pzbuy"):
            status = {"pzno": "skipped", "pzbuy": "bought"}.get(action)
            if status:
                with db.tx() as c:
                    pause = ledger.resolve_pause(c, int(parts[1]), status, today)
                    saved = finance.saved_by_pauses(c)
                if pause is None:
                    await done("Isso já foi resolvido.")
                elif status == "skipped":
                    await done(
                        f"Boa. {brl(pause['amount_cents'])} ficaram com você. Total evitado até agora: <b>{brl(saved)}</b>."
                    )
                else:
                    await done(f"Registrado: {html.escape(pause['item'])}, {brl(pause['amount_cents'])}.")
        elif action == "ob":
            with db.tx() as c:
                in_setup = onboarding.active(c)
            await self.tg.api("editMessageReplyMarkup", chat_id=chat, message_id=message_id)
            if in_setup:
                await self.continue_onboarding(chat, data[3:])
        elif action == "ugoal":
            with db.tx() as c:
                c.execute("DELETE FROM goal_deposits WHERE id = ?", (int(parts[1]),))
            await done("Desfeito.")
        elif action == "chkno":
            self.pending.pop(parts[1], None)
            await done("Certo, não registrei nada. Pode mandar de novo com o valor certo.")
        elif action == "chk":
            info = self.pending.pop(parts[1], None)
            if info is None:
                await done("Esse pedido expirou. Mande de novo.")
                return
            with db.tx() as c:
                captured = ops.capture(c, info["text"], today, "telegram", confirmed=True)
                reply, markup = self._log_reply(c, captured, today) if captured else ("Não consegui registrar.", None)
            await done(reply, markup)
        elif action == "imp":
            pending = self.pending.pop(parts[1], None)
            if pending is None:
                await done("Esse pedido expirou. Mande o arquivo de novo.")
                return
            await done("Importando…")
            await self._import(chat, pending["items"], int(parts[2]))

    async def _purchase_choice(self, action: str, token: str, done: Any, today: date) -> None:
        info = self.pending.pop(token, None)
        if info is None:
            await done("Esse pedido expirou. Pergunte de novo.")
            return
        item, amount, installments = info["item"], info["amount"], info["installments"]
        with db.tx() as c:
            if action == "p24":
                ledger.create_pause(c, item, amount, installments)
                text = f"Guardado. Amanhã neste horário eu pergunto se você ainda quer: {html.escape(item)}."
            elif action == "pno":
                pause = ledger.create_pause(c, item, amount, installments)
                ledger.resolve_pause(c, pause, "skipped", today)
                text = f"Boa. {brl(amount)} ficaram com você. Total evitado até agora: <b>{brl(finance.saved_by_pauses(c))}</b>."
            else:
                pause = ledger.create_pause(c, item, amount, installments)
                ledger.resolve_pause(c, pause, "bought", today)
                text = f"Registrado: {html.escape(item)}, {brl(amount)}. {ops.feedback(c, today, today)}"
        await done(text)


def today_message(c: Any, today: date, skip_tomorrow: bool = False) -> tuple[str, dict | None]:
    t = finance.today_status(c, today)
    if t.status == "setup":
        return (
            "Para eu calcular seu limite diário, preciso da sua renda. Mande /comecar e eu pergunto o que falta.",
            None,
        )
    if t.status == "starting":
        return (
            f"Seu limite diário começa em 1º de {finance.nextfinance.month_name(today)}. Até lá, é só ir registrando o que gastar.",
            None,
        )
    if t.status == "broken":
        head = f"As contas do mês não fecham: faltam <b>{brl(-t.budget.available)}</b>. Não há gasto seguro hoje."
    elif t.left_today < 0:
        head = f"Hoje passou <b>{brl(-t.left_today)}</b> do limite. Amanhã: {brl(t.tomorrow)}."
    elif t.spent_today:
        head = f"Ainda cabe <b>{brl(t.left_today)}</b> hoje. Já foi {brl(t.spent_today)}."
    else:
        head = f"Hoje você pode gastar <b>{brl(t.left_today)}</b>."
    lines = [head, f"Faltam {t.days_left} dias; restam {brl(t.budget.remaining)} no mês."]
    # O bom-dia não repete o que o alerta de véspera avisa logo depois.
    items = [i for i in finance.upcoming(c, today, 3) if not (skip_tomorrow and i["days"] == 1)]
    buttons = []
    if items:
        lines.append("")
        for i in items[:5]:
            lines.append(f"{when_label(i['days'], i['due'])}: {html.escape(i['name'])} {brl(i['amount_cents'])}")
            buttons.append([(f"Paguei {i['name']}"[:40], f"paid:{i['type']}:{i['id']}:{i['month']}")])
    focus = finance.focus(c, today)
    if focus and focus["tone"] != "neutral":
        lines += ["", f"<b>{html.escape(focus['title'])}.</b> {html.escape(focus['body'])}"]
    return "\n".join(lines), kb(*buttons) if buttons else None


def _chat_of(update: dict) -> int | None:
    if "message" in update:
        return update["message"]["chat"]["id"]
    if "callback_query" in update and update["callback_query"].get("message"):
        return update["callback_query"]["message"]["chat"]["id"]
    return None


def when_label(days: int, due: str) -> str:
    if days < 0:
        return f"Atrasada há {-days}d"
    if days == 0:
        return "Hoje"
    if days == 1:
        return "Amanhã"
    return f"{due[8:10]}/{due[5:7]}"


WELCOME = "Oi. Sou a Força. Vamos organizar isso juntos, sem drama."

HELP = """<b>Registrar um gasto</b>
<code>mercado 87</code>
<code>tv 1200 10x nubank</code>
Pode ser áudio, foto ou o arquivo do extrato.

<b>Guardar dinheiro</b>
<code>guardei 200 na reserva</code>

<b>Antes de comprar</b>
<code>posso comprar um tênis de 400?</code>

Para o resto, é só pedir: "como foi meu mês?", "apaga o último gasto", "cria a categoria Pilates".
Para cadastrar contas, cartões e dívidas passo a passo, mande /comecar."""
