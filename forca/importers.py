"""Lê extrato e fatura (OFX e CSV dos bancos brasileiros) e evita duplicar o que
já foi registrado pelo Telegram. PDF e foto vão pela IA, em ai.py."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .finance import add_months, invoice_month_for, month_of
from .ledger import add_expense, add_income, ensure_started, insert_transaction, learned_categories
from .parser import guess_category, normalize


@dataclass
class Item:
    day: date
    amount_cents: int  # positivo = saiu; negativo = entrou
    description: str


class ImportFailed(ValueError):
    pass


# ---------- leitura ----------


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_money(raw: str) -> int | None:
    text = raw.strip().replace("R$", "").replace(" ", "").replace(" ", "")
    negative = text.startswith("-") or text.endswith("-") or (text.startswith("(") and text.endswith(")"))
    text = text.strip("-+()")
    if not text or not re.fullmatch(r"[\d.,]+", text):
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
    elif "," in text:
        decimal = ","
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        decimal = None
    else:
        decimal = "."
    if decimal:
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    else:
        text = text.replace(".", "")
    try:
        cents = round(float(text) * 100)
    except ValueError:
        return None
    return -cents if negative else cents


def _parse_date(raw: str) -> date | None:
    text = raw.strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _ofx_tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}>([^<\r\n]*)", block, re.I)
    return match[1].strip() if match else ""


def parse_ofx(text: str) -> tuple[list[Item], bool]:
    items = []
    is_card = "<CREDITCARDMSGSRSV1>" in text.upper()
    for block in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", text, re.S | re.I):
        posted, amount = _ofx_tag(block, "DTPOSTED")[:8], _ofx_tag(block, "TRNAMT")
        if not posted or not amount:
            continue
        try:
            day = datetime.strptime(posted, "%Y%m%d").date()
            value = round(float(amount.replace(",", ".")) * 100)
        except ValueError:
            continue
        description = _ofx_tag(block, "MEMO") or _ofx_tag(block, "NAME") or "Sem descrição"
        # No OFX, saída é negativa tanto em conta quanto em cartão.
        items.append(Item(day, -value, description))
    return items, is_card


_DATE_COLS = ("data", "date", "dt", "data lancamento", "data da compra", "lancamento")
_DESC_COLS = (
    "descricao",
    "title",
    "historico",
    "description",
    "estabelecimento",
    "lancamento",
    "detalhes",
    "memo",
    "titulo",
)
_AMOUNT_COLS = ("valor", "amount", "valor (r$)", "valor r$", "value", "quantia")


def parse_csv(text: str) -> tuple[list[Item], bool]:
    """Encontra a linha de cabeçalho (bancos costumam pôr lixo antes dela)
    e deduz o sentido do valor: fatura lista compras como positivas, extrato como negativas."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ImportFailed("O arquivo está vazio.")
    sample = "\n".join(lines[:20])
    delimiter = max(";,\t|", key=sample.count)
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))

    header_at, cols = None, {}
    for index, row in enumerate(rows[:15]):
        names = [normalize(cell) for cell in row]
        found = _find_columns(names)
        if "date" in found and "amount" in found:
            header_at, cols = index, found
            break
    if header_at is None:
        raise ImportFailed("Não encontrei as colunas de data e valor neste CSV.")

    raw_items = []
    for row in rows[header_at + 1 :]:
        if len(row) <= max(cols.values()):
            continue
        day = _parse_date(row[cols["date"]])
        value = _parse_money(row[cols["amount"]])
        if day is None or value is None or value == 0:
            continue
        description = row[cols["desc"]].strip() if "desc" in cols else "Sem descrição"
        raw_items.append((day, value, description or "Sem descrição"))
    if not raw_items:
        raise ImportFailed("Não encontrei lançamentos neste CSV.")

    positives = sum(1 for _, v, _ in raw_items if v > 0)
    # "Pagamento recebido" só existe em fatura; estornos podem derrubar a proporção.
    has_marker = any("pagamento recebido" in normalize(desc) for _, _, desc in raw_items)
    is_invoice = has_marker or positives / len(raw_items) > 0.7
    items = [Item(d, v if is_invoice else -v, desc) for d, v, desc in raw_items]
    return items, is_invoice


def _find_columns(names: list[str]) -> dict:
    found: dict = {}
    for index, name in enumerate(names):
        if "date" not in found and name in _DATE_COLS:
            found["date"] = index
        elif "amount" not in found and (name in _AMOUNT_COLS or name.startswith("valor")):
            found["amount"] = index
        elif "desc" not in found and name in _DESC_COLS:
            found["desc"] = index
    return found


def parse_file(filename: str, raw: bytes) -> tuple[list[Item], bool]:
    text = _decode(raw)
    lower = filename.lower()
    if lower.endswith((".ofx", ".qfx")) or "<OFX>" in text[:4000].upper() or "<STMTTRN>" in text.upper():
        items, is_card = parse_ofx(text)
        if not items:
            raise ImportFailed("Não encontrei lançamentos neste OFX.")
        return items, is_card
    if lower.endswith((".csv", ".txt", ".tsv")):
        return parse_csv(text)
    raise ImportFailed("Por enquanto leio OFX e CSV aqui. Para PDF ou foto, mande pelo Telegram.")


# ---------- gravação ----------

_INTERNAL = re.compile(
    r"\b(pagamento (de )?fatura|pgto\.? fatura|pag\.? fatura|fatura (do )?cartao|pagamento recebido|pagamento efetuado|"
    r"transferencia entre contas|aplicacao|resgate|rdb|cdb|saldo anterior|saldo do dia)\b"
)
_INSTALLMENT = re.compile(r"(?:parcela\s*)?\b(\d{1,2})\s*(?:/|de)\s*(\d{1,2})\b")


def _hash(day: date, amount: int, description: str, occurrence: int) -> str:
    key = f"{day.isoformat()}|{amount}|{normalize(description)}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _find_manual_match(c: sqlite3.Connection, item: Item, used: set[int]) -> int | None:
    """Algo registrado à mão, de mesmo valor, até 3 dias antes da data do banco
    (ou 1 depois). Banco costuma lançar depois, então janela assimétrica."""
    start = (item.day - timedelta(days=3)).isoformat()
    end = (item.day + timedelta(days=1)).isoformat()
    rows = c.execute(
        "SELECT id, date, card_id FROM transactions WHERE amount_cents = ? AND date BETWEEN ? AND ? AND source NOT IN ('import', 'opening') AND external_hash IS NULL AND kind = ? ORDER BY ABS(julianday(date) - julianday(?))",
        (abs(item.amount_cents), start, end, "expense" if item.amount_cents > 0 else "income", item.day.isoformat()),
    ).fetchall()
    for r in rows:
        if r["id"] not in used:
            return r["id"]
    return None


def _tidy(description: str) -> str:
    """Banco escreve 'POSTO SHELL'; o extrato fica melhor como 'Posto Shell'."""
    text = " ".join(description.split())
    return text.title() if text.isupper() else text


def import_items(
    c: sqlite3.Connection, items: list[Item], card: sqlite3.Row | None, today: date, source: str = "import"
) -> dict:
    batch = uuid.uuid4().hex[:12]
    ensure_started(c, today)
    learned = learned_categories(c)
    summary = {
        "batch_id": batch,
        "added": 0,
        "matched": 0,
        "already": 0,
        "ignored": 0,
        "total_cents": 0,
        "uncategorized": 0,
    }
    used: set[int] = set()
    seen: dict[tuple, int] = {}
    for item in items:
        item = Item(item.day, item.amount_cents, _tidy(item.description))
        # Duas compras iguais no mesmo dia são reais: o índice as mantém distintas.
        key = (item.day, item.amount_cents, normalize(item.description))
        seen[key] = seen.get(key, 0) + 1
        ext = _hash(item.day, item.amount_cents, item.description, seen[key])
        if c.execute("SELECT 1 FROM transactions WHERE external_hash = ?", (ext,)).fetchone():
            summary["already"] += 1
            continue
        norm = normalize(item.description)
        if _INTERNAL.search(norm):
            summary["ignored"] += 1
            continue

        match = _find_manual_match(c, item, used)
        if match:
            used.add(match)
            c.execute("UPDATE transactions SET external_hash = ? WHERE id = ?", (ext, match))
            summary["matched"] += 1
            continue

        if item.amount_cents < 0:
            if card is not None:
                # Estorno na fatura: abate da fatura e do orçamento em que a compra pesou.
                invoice = invoice_month_for(item.day, card["closing_day"], card["due_day"])
                insert_transaction(
                    c,
                    "expense",
                    item.amount_cents,
                    item.description,
                    guess_category(item.description, learned),
                    item.day,
                    month_of(item.day),
                    card_id=card["id"],
                    invoice_month=invoice,
                    source=source,
                    batch_id=batch,
                    external_hash=ext,
                )
            else:
                add_income(
                    c, -item.amount_cents, item.description, item.day, source=source, batch_id=batch, external_hash=ext
                )
            summary["added"] += 1
            continue

        installment = _INSTALLMENT.search(norm) if card is not None else None
        if installment and 1 <= int(installment[1]) <= int(installment[2]) <= 72 and int(installment[2]) > 1:
            added = _import_installment(
                c, item, card, int(installment[1]), int(installment[2]), batch, ext, learned, source
            )
            summary["added" if added else "already"] += 1
            if added:
                summary["total_cents"] += item.amount_cents
            continue

        result = add_expense(
            c,
            item.amount_cents,
            item.description,
            item.day,
            card=card,
            source=source,
            batch_id=batch,
            external_hash=ext,
            category=None if card is None else guess_category(item.description, learned),
        )
        summary["added"] += 1
        summary["total_cents"] += item.amount_cents
        if result["category"] == "outros":
            summary["uncategorized"] += 1
    return summary


def _import_installment(
    c: sqlite3.Connection,
    item: Item,
    card: sqlite3.Row,
    number: int,
    total: int,
    batch: str,
    ext: str,
    learned: dict,
    source: str,
) -> bool:
    """Parcela de fatura. A próxima fatura trará a mesma compra: se ela já foi projetada
    na importação anterior, atualiza em vez de duplicar; senão, projeta as restantes."""
    base = normalize(_INSTALLMENT.sub(" ", normalize(item.description)))
    invoice = invoice_month_for(item.day, card["closing_day"], card["due_day"])
    for row in c.execute(
        "SELECT * FROM transactions WHERE card_id = ? AND installment_no = ? AND installment_total = ? AND ABS(amount_cents - ?) <= 1",
        (card["id"], number, total, item.amount_cents),
    ).fetchall():
        existing = normalize(_INSTALLMENT.sub(" ", normalize(row["description"])))
        if existing == base and not row["external_hash"]:
            c.execute("UPDATE transactions SET external_hash = ? WHERE id = ?", (ext, row["id"]))
            return False

    category = guess_category(item.description, learned)
    group = uuid.uuid4().hex
    month = month_of(item.day)
    for offset, current in enumerate(range(number, total + 1)):
        insert_transaction(
            c,
            "expense",
            item.amount_cents,
            item.description,
            category,
            item.day if offset == 0 else item.day + timedelta(days=30 * offset),
            add_months(month, offset),
            committed=1 if current > 1 else 0,
            card_id=card["id"],
            invoice_month=add_months(invoice, offset),
            group_id=group,
            installment_no=current,
            installment_total=total,
            source=source,
            batch_id=batch,
            external_hash=ext if offset == 0 else None,
        )
    return True


def undo_batch(c: sqlite3.Connection, batch_id: str) -> int:
    rows = c.execute("SELECT * FROM transactions WHERE batch_id = ?", (batch_id,)).fetchall()
    for r in rows:
        if r["debt_id"]:
            c.execute(
                "UPDATE debts SET balance_cents = balance_cents + ?, active = 1 WHERE id = ?",
                (r["amount_cents"], r["debt_id"]),
            )
        c.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
    return len(rows)
