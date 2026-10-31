import pytest

from forca import config, db


@pytest.fixture()
def c(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db.init()
    conn = db.connect()
    yield conn
    conn.commit()
    conn.close()
