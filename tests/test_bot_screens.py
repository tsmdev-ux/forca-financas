import asyncio
from datetime import date

import pytest

from forca import bot, db, ledger, ops

CHAT = 1


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send(self, chat, text, markup=None):
        self.sent.append((text, markup))

    async def api(self, method, **params):
        return {}


@pytest.fixture()
def screen(c):
    telegram = FakeTelegram()
    b = bot.Bot(telegram)

    def show(method):
        c.commit()
        asyncio.run(getattr(b, method)(CHAT))
        return telegram.sent[-1]

    return show


def seed(c):
    ops.add_recurring(c, "income", "Salário", 500000, 5)
    ops.add_recurring(c, "expense", "Aluguel", 150000, 20)
    ledger.ensure_started(c, date(2026, 11, 1))


def test_month_screen_shows_the_math(c, screen):
    seed(c)
    ledger.add_expense(c, 8700, "Mercado", date(2026, 11, 10))
    text, _ = screen("send_month")
    assert "novembro de 2026" in text
    for expected in ("R$ 5.000", "R$ 1.500", "R$ 3.500", "R$ 87", "R$ 3.413", "Mercado"):
        assert expected in text


def test_pay_screen_lists_bills_with_paid_buttons(c, screen):
    seed(c)
    ops.add_card(c, "Nubank", 3, 10)
    text, markup = screen("send_bills")
    assert "Aluguel" in text and "Nubank" in text and "fecha em" in text
    assert markup["inline_keyboard"][0][0]["callback_data"].startswith("paid:bill:")


def test_pay_screen_when_nothing_is_due(screen):
    assert "Nada a vencer" in screen("send_bills")[0]


def test_debts_screen_with_plan(c, screen):
    ops.add_debt(c, "Empréstimo", 100000, 2.5, 20000, 15)
    text, _ = screen("send_debts")
    assert "R$ 1.000" in text and "2,5%" in text and "fica livre em" in text


def test_debts_screen_warns_when_it_never_ends(c, screen):
    ops.add_debt(c, "Rotativo", 500000, 14, 30000, 10, True)
    text, _ = screen("send_debts")
    assert "não acabam nunca" in text and "atrasada" in text


def test_debts_screen_empty(screen):
    assert "Nenhuma dívida" in screen("send_debts")[0]


def test_mute_toggles(c, screen):
    assert "pausados" in screen("toggle_mute")[0]
    with db.tx() as check:
        assert db.get_setting(check, "nudges_off") == "1"
    assert "ligados" in screen("toggle_mute")[0]


def test_undo_last_entry(c, screen):
    ledger.add_expense(c, 100, "Café", date(2026, 11, 10))
    assert "Café" in screen("undo_last")[0]
    assert "nada para desfazer" in screen("undo_last")[0]
