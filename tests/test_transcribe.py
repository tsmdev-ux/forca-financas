import asyncio
from types import SimpleNamespace

from forca import transcribe


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, path, **options):
        self.calls.append(options)
        return iter([SimpleNamespace(text=" Mercado "), SimpleNamespace(text="87. ")]), None


def test_joins_segments_and_forces_portuguese(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(transcribe, "_model", model)
    assert asyncio.run(transcribe.transcribe(b"audio")) == "Mercado 87."
    assert model.calls[0]["language"] == "pt"


def test_loads_model_only_once(monkeypatch):
    loads = []

    def load():
        loads.append(1)
        return FakeModel()

    monkeypatch.setattr(transcribe, "_load", load)
    monkeypatch.setattr(transcribe, "_model", None)
    assert asyncio.run(transcribe.transcribe(b"audio")) == "Mercado 87."
    assert len(loads) == 1


def test_failure_returns_none_instead_of_crashing(monkeypatch):
    def broken():
        raise RuntimeError("sem modelo")

    monkeypatch.setattr(transcribe, "_load", broken)
    assert asyncio.run(transcribe.transcribe(b"audio")) is None
