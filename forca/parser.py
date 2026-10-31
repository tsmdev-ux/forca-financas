"""Entende "mercado 87,50" sem chamar IA: rápido, de graça e funciona offline.
Quando a frase é ambígua, devolve None e quem chamou decide (normalmente o agente)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


CATEGORIES = {
    "mercado": "mercado supermercado feira hortifruti padaria acougue atacadao assai carrefour sacolao",
    "comida": "almoco jantar lanche restaurante ifood rappi delivery pizza hamburguer cafe marmita sushi bar lanchonete cerveja acai sorvete mcdonalds burger",
    "transporte": "uber 99 gasolina combustivel posto onibus metro estacionamento pedagio taxi oficina shell ipiranga",
    "moradia": "aluguel condominio reforma",
    "servicos": "diarista faxina encanador eletricista lavanderia conserto costureira contador advogado cartorio chaveiro servico frete",
    "contas": "luz energia agua internet telefone celular gas vivo claro tim enel sabesp",
    "assinaturas": "netflix spotify prime disney hbo max youtube icloud assinatura academia smartfit",
    "saude": "farmacia remedio medico dentista exame consulta plano drogaria drogasil terapia",
    "lazer": "cinema show ingresso jogo balada passeio festa steam",
    "viagem": "viagem hotel pousada passagem airbnb booking decolar latam gol azul",
    "compras": "shopping amazon shopee magalu eletronico",
    "roupas": "roupa tenis sapato camisa calca vestido renner shein zara",
    "beleza": "salao barbearia cabeleireiro manicure perfume cosmetico boticario sephora",
    "educacao": "curso escola faculdade livro mensalidade",
    "familia": "filho filha creche fralda mae pai",
    "pets": "pet racao veterinario petshop petz cobasi",
    "presentes": "presente aniversario doacao dizimo",
    "impostos": "imposto ipva iptu irpf multa taxa darf",
}
# Onde o gasto costuma ser escolha, não necessidade: é aqui que os alertas de padrão olham.
DISCRETIONARY = {"comida", "lazer", "compras", "assinaturas", "roupas", "beleza", "viagem"}
ALL_CATEGORIES = [*list(CATEGORIES), "dividas", "renda", "outros"]
# Fora da lista de escolha: são preenchidas pelo próprio app.
SYSTEM_CATEGORIES = {"dividas", "renda", "outros"}

CATEGORY_SEED = [
    ("mercado", "Mercado", "cart"),
    ("comida", "Alimentação", "plate"),
    ("transporte", "Transporte", "car"),
    ("moradia", "Moradia", "home"),
    ("servicos", "Serviços", "tool"),
    ("contas", "Contas", "bulb"),
    ("assinaturas", "Assinaturas", "repeat"),
    ("saude", "Saúde", "health"),
    ("lazer", "Lazer", "ticket"),
    ("viagem", "Viagem", "plane"),
    ("compras", "Compras", "bag"),
    ("roupas", "Roupas", "shirt"),
    ("beleza", "Beleza", "scissors"),
    ("educacao", "Educação", "book"),
    ("familia", "Família", "people"),
    ("pets", "Pets", "paw"),
    ("presentes", "Presentes", "gift"),
    ("impostos", "Impostos", "receipt"),
    ("outros", "Outros", "dot"),
    ("dividas", "Dívidas", "card"),
    ("renda", "Renda", "coin"),
]

_KEYWORDS = {word: cat for cat, words in CATEGORIES.items() for word in words.split()}
_PHRASES = {"mercado livre": "compras", "pao de acucar": "mercado"}


def guess_category(description: str, learned: dict | None = None) -> str:
    text = normalize(description)
    if learned:
        for merchant, category in learned.items():
            if merchant and merchant in text:
                return category
    for phrase, category in _PHRASES.items():
        if phrase in text:
            return category
    for word in re.findall(r"[a-z0-9]+", text):
        if word in _KEYWORDS:
            return _KEYWORDS[word]
    return "outros"


@dataclass
class Parsed:
    kind: str  # expense | income | zero_day | recurring_income | recurring_expense | goal_deposit
    amount_cents: int = 0
    description: str = ""
    category: str = "outros"
    date: date | None = None
    installments: int = 1  # em recorrentes, guarda o dia do mês
    card_hint: str | None = None


_AMOUNT = re.compile(
    r"(?<![\w/.,])(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(\s*(?:k|mil)\b)?(?:\s*(?:reais|real|conto|contos)\b)?(?![\w/])",
    re.I,
)
_QUESTION = re.compile(
    r"\?|^(quanto|quantos|quantas|como|qual|quais|onde|quando|por ?que|posso|devo|da pra|consigo|me (ajuda|explica|diz|fala)|o que|tenho|vale a pena)\b"
)
_ZERO = re.compile(
    r"^(0|zero|nada|nenhum gasto|sem gasto|nao gastei( nada)?|hoje (foi )?(zero|nada)|gastei nada)( hoje)?[.!]*$"
)
_INCOME = re.compile(
    r"\b(ganhei|ganhou|recebi|receita|salario|pagamento recebido|caiu|entrou|renda|freela|pix recebido|adiantamento|13o)\b"
)
_RECURRING = re.compile(r"\b(?:todo|cada|sempre)\s+(?:o\s+)?dia\s+(\d{1,2})\b")
_EARNS = re.compile(r"\b(ganho|ganhou|ganhei|recebo|recebe|salario|renda)\b")
# Pedido para mudar algo, ou frase que aponta para o que já foi dito, nunca é um gasto novo.
_COMMAND = re.compile(
    r"\b(excl\w+|apag\w+|remov\w+|delet\w+|desfa\w+|cancel\w+|corrig\w+|mud\w+|alter\w+|troc\w+|atualiz\w+|edit\w+|"
    r"desativ\w+|tir[ae]r?|err\w+|cadastr\w+|adicion\w+|coloc\w+|ajust\w+|essa|esse|esses|essas|isso|aquela|aquele)\b"
)
# Frases de cadastro que parecem gasto mas não são: ficam para o agente.
_NOT_A_LOG = re.compile(r"^(devo|ganho|recebo|fecha|vence|tenho|meu|minha)\b|\b(fecha|vence)\s+dia\b|%")
_NOISE = re.compile(
    r"^(gastei|paguei|comprei|foi|com|no|na|nos|nas|de|do|da|em|um|uma|o|a|r\$|reais|real|hoje|pix|debito|dinheiro)$"
)


def to_cents(raw: str, suffix: str | None) -> int:
    if "," in raw:
        value = float(raw.replace(".", "").replace(",", "."))
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        value = float(raw.replace(".", ""))
    else:
        value = float(raw)
    if suffix:
        value *= 1000
    return round(value * 100)


def _extract_date(text: str, today: date) -> tuple[str, date | None]:
    for pattern, delta in ((r"\banteontem\b", 2), (r"\bontem\b", 1)):
        if re.search(pattern, text):
            return re.sub(pattern, " ", text), today - timedelta(days=delta)
    match = re.search(r"\b(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if match:
        day, month, year = int(match[1]), int(match[2]), match[3]
        year_value = (2000 + int(year) if len(year) == 2 else int(year)) if year else today.year
        try:
            found = date(year_value, month, day)
        except ValueError:
            return text, None
        if not year and found > today:
            found = found.replace(year=found.year - 1)
        return text[: match.start()] + " " + text[match.end() :], found
    match = re.search(r"\bdia\s+(\d{1,2})\b", text)
    if match:
        day = int(match[1])
        try:
            found = today.replace(day=day)
        except ValueError:
            return text, None
        if found > today:  # "dia 28" no dia 3 fala do mês passado
            previous = today.replace(day=1) - timedelta(days=1)
            try:
                found = previous.replace(day=day)
            except ValueError:
                return text, None
        return text[: match.start()] + " " + text[match.end() :], found
    return text, None


def parse(text: str, today: date, card_names: tuple[str, ...] = (), learned: dict | None = None) -> Parsed | None:
    original = text.strip()
    if not original or len(original) > 90 or "\n" in original:
        return None
    norm = normalize(original)
    if _ZERO.match(norm):
        return Parsed(kind="zero_day", date=today)
    if _QUESTION.search(norm):
        return None

    if _COMMAND.search(norm):
        return None
    if _SAVED.match(norm):
        return _parse_goal_deposit(norm, original)
    recurring = _RECURRING.search(norm)
    if recurring:
        return _parse_recurring(norm, original, recurring)
    if _NOT_A_LOG.search(norm):
        return None

    work, found_date = _extract_date(norm, today)

    installments = 1
    match = re.search(r"\b(?:em\s+)?(\d{1,2})\s*x\b", work)
    if match:
        installments = int(match[1])
        work = work[: match.start()] + " " + work[match.end() :]
    if installments < 1 or installments > 72:
        return None

    card_hint = None
    for name in sorted(card_names, key=len, reverse=True):
        norm_name = normalize(name)
        match = re.search(r"\b(?:(?:no|na|cartao|credito)\s+)*" + re.escape(norm_name) + r"\b", work)
        if match:
            card_hint = name
            work = work[: match.start()] + " " + work[match.end() :]
            break
    if card_hint is None:
        match = re.search(r"\b(?:no\s+|na\s+)?(cartao|credito)\b", work)
        if match:
            card_hint = "*"
            work = work[: match.start()] + " " + work[match.end() :]

    amounts = list(_AMOUNT.finditer(work))
    if len(amounts) != 1:
        return None  # sem valor ou mais de um número: deixa para quem entende contexto
    amount = to_cents(amounts[0][1], amounts[0][2])
    if amount <= 0:
        return None
    rest = work[: amounts[0].start()] + " " + work[amounts[0].end() :]

    # A transcrição de áudio pontua as frases: "O Uber 25 R$."
    rest = re.sub(r"[.,;:!]+(?=\s|$)", " ", rest)
    is_income = bool(_INCOME.search(rest))
    words = [w for w in rest.split() if not _NOISE.match(w)]
    if is_income:
        words = [w for w in words if w not in {"recebi", "caiu", "entrou", "ganhei", "ganhou"}]
    if len(words) > 4:
        return None
    description = " ".join(words).strip(" .,-!")
    if not description:
        description = "Entrada" if is_income else "Sem descrição"

    pretty = _restore_accents(description, original)
    if is_income:
        return Parsed("income", amount, pretty, "renda", found_date or today, 1, None)
    return Parsed(
        "expense",
        amount,
        pretty,
        guess_category(description, learned),
        found_date or today,
        installments,
        card_hint,
    )


_SAVED = re.compile(r"^(guardei|poupei|depositei|juntei|economizei)\b")


def _parse_goal_deposit(norm: str, original: str) -> Parsed | None:
    """ "guardei 200 na reserva": dinheiro guardado não é gasto."""
    amounts = list(_AMOUNT.finditer(norm))
    if len(amounts) != 1:
        return None
    amount = to_cents(amounts[0][1], amounts[0][2])
    if amount <= 0:
        return None
    rest = _SAVED.sub(" ", norm[: amounts[0].start()] + " " + norm[amounts[0].end() :])
    words = [
        w
        for w in re.sub(r"[.,;:!]+(?=\s|$)", " ", rest).split()
        if not _NOISE.match(w) and w not in {"para", "pra", "meta", "minha"}
    ]
    return Parsed("goal_deposit", amount, " ".join(words))


def _parse_recurring(norm: str, original: str, match: re.Match[str]) -> Parsed | None:
    """ "aluguel 1200 todo dia 10" é conta fixa; "ganho 4200 todo dia 5" é renda."""
    day = int(match[1])
    work = norm[: match.start()] + " " + norm[match.end() :]
    amounts = list(_AMOUNT.finditer(work))
    if not 1 <= day <= 31 or len(amounts) != 1:
        return None
    amount = to_cents(amounts[0][1], amounts[0][2])
    if amount <= 0:
        return None
    rest = work[: amounts[0].start()] + " " + work[amounts[0].end() :]
    earns = bool(_EARNS.search(rest))
    words = [
        w
        for w in rest.split()
        if not _NOISE.match(w) and w not in {"ganho", "ganhou", "ganhei", "recebo", "recebe", "pago"}
    ]
    description = " ".join(words).strip(" .,-!")
    if not description:
        if not earns:
            return None
        return Parsed("recurring_income", amount, "Salário", installments=day)
    pretty = _restore_accents(description, original)
    return Parsed("recurring_income" if earns else "recurring_expense", amount, pretty, date=None, installments=day)


def _restore_accents(normalized_desc: str, original: str) -> str:
    """A busca roda sem acento, mas a descrição guardada usa o que foi digitado."""
    by_norm = {normalize(w): w for w in re.findall(r"[^\s]+", original)}
    words = [by_norm.get(w, w) for w in normalized_desc.split()]
    result = " ".join(words)
    return result[:1].upper() + result[1:]


_PURCHASE_QUESTION = re.compile(
    r"\b(posso|devo|vale a pena|quero|queria|pensando em|to pensando|estou pensando|da pra|consigo)\b.*\b(comprar|gastar|pegar|parcelar|levar)?\b"
)


def parse_purchase_question(text: str) -> tuple[str, int, int] | None:
    """'posso comprar um tênis de 400?' -> ('tênis', 40000, 1)"""
    norm = normalize(text)
    if not re.search(r"\b(comprar|gastar|parcelar|pegar|levar)\b", norm):
        return None
    if not _PURCHASE_QUESTION.search(norm):
        return None
    installments = 1
    match = re.search(r"\b(?:em\s+)?(\d{1,2})\s*x\b", norm)
    if match:
        installments = int(match[1])
        norm = norm[: match.start()] + " " + norm[match.end() :]
    amounts = list(_AMOUNT.finditer(norm))
    if len(amounts) != 1:
        return None
    cents = to_cents(amounts[0][1], amounts[0][2])
    if cents <= 0:
        return None
    rest = norm[: amounts[0].start()] + " " + norm[amounts[0].end() :]
    rest = re.sub(
        r"\b(posso|devo|vale|a|pena|quero|queria|pensando|em|to|estou|da|pra|consigo|comprar|gastar|parcelar|pegar|levar|um|uma|o|de|por|r\$|reais|eu|hoje|agora|isso|esse|essa)\b",
        " ",
        rest,
    )
    item = " ".join(re.sub(r"[?!.,]", " ", rest).split())
    return (_restore_accents(item, text) if item else "Essa compra", cents, installments)
