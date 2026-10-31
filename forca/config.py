"""Configuração lida do ambiente. Nada aqui é obrigatório para o app abrir;
o que falta só desliga a parte correspondente (bot, IA ou áudio)."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("FORCA_DATA_DIR", "data"))
DB_PATH = DATA_DIR / "forca.db"
BACKUP_DIR = DATA_DIR / "backups"

TZ = ZoneInfo(os.environ.get("FORCA_TZ", "America/Sao_Paulo"))
BASE_URL = os.environ.get("FORCA_BASE_URL", "http://localhost:8000").rstrip("/")
PASSWORD = os.environ.get("FORCA_PASSWORD", "")
SECRET = os.environ.get("FORCA_SECRET", "")
PAIR_CODE = os.environ.get("FORCA_PAIR_CODE", "")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("FORCA_MODEL", "deepseek-flash")
WHISPER_MODEL = os.environ.get("FORCA_WHISPER_MODEL", "base")


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()
