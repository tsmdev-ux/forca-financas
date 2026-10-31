"""Áudio do Telegram vira texto na própria VPS, sem mandar a voz para ninguém."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from typing import Any

from . import config

log = logging.getLogger("forca.transcribe")
_model: Any | None = None


def _load() -> Any:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            config.WHISPER_MODEL, device="cpu", compute_type="int8", download_root=str(config.DATA_DIR / "whisper")
        )
    return _model


def _run(raw: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".ogg") as f:
        f.write(raw)
        f.flush()
        segments, _ = _load().transcribe(f.name, language="pt", beam_size=1, vad_filter=False)
        return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(raw: bytes) -> str | None:
    try:
        return await asyncio.to_thread(_run, raw)
    except Exception:
        log.exception("Falha ao transcrever")
        return None
