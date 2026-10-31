import getpass
import sys

import pytest

from forca import backup, restore


@pytest.fixture()
def encrypted(tmp_path):
    path = tmp_path / "copia.forca"
    path.write_bytes(backup.encrypt(b"banco de dados", "senha certa"))
    return path


def run(monkeypatch, password, *args):
    monkeypatch.setattr(getpass, "getpass", lambda _: password)
    monkeypatch.setattr(sys, "argv", ["restore", *map(str, args)])
    return restore.main()


def test_restores_with_right_password(monkeypatch, encrypted, tmp_path):
    target = tmp_path / "saida.db"
    assert run(monkeypatch, "senha certa", encrypted, target) == 0
    assert target.read_bytes() == b"banco de dados"


def test_wrong_password_writes_nothing(monkeypatch, encrypted, tmp_path, capsys):
    target = tmp_path / "saida.db"
    assert run(monkeypatch, "senha errada", encrypted, target) == 1
    assert not target.exists()
    assert "Senha incorreta" in capsys.readouterr().out


def test_never_overwrites_existing_file(monkeypatch, encrypted, tmp_path):
    target = tmp_path / "saida.db"
    target.write_bytes(b"banco atual")
    assert run(monkeypatch, "senha certa", encrypted, target) == 1
    assert target.read_bytes() == b"banco atual"


def test_usage_message(monkeypatch, capsys):
    assert run(monkeypatch, "x") == 2
    assert "Uso:" in capsys.readouterr().out
