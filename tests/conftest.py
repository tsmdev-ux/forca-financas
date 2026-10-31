from datetime import date, datetime

import pytest

from forca import config, db

# Data fixa: nenhum teste pode depender do dia em que o CI roda.
FIXED_TODAY = date(2026, 11, 11)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(config, "today", lambda: FIXED_TODAY)
    monkeypatch.setattr(config, "now", lambda: datetime(2026, 11, 11, 12, 0, tzinfo=config.TZ))


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init()
    conn = db.connect()
    yield conn
    conn.commit()
    conn.close()
