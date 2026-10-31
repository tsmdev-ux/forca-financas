"""Cópia criptografada para fora da VPS. Abre só com a senha do app, que não fica no arquivo."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import db

MAGIC = b"FORCA1"
SALT_SIZE, NONCE_SIZE = 16, 12


class WrongPassword(ValueError):
    pass


def _key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def encrypt(data: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(SALT_SIZE), os.urandom(NONCE_SIZE)
    return MAGIC + salt + nonce + AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise WrongPassword("Este arquivo não é um backup da Força.")
    salt = blob[len(MAGIC) : len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE : len(MAGIC) + SALT_SIZE + NONCE_SIZE]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, blob[len(MAGIC) + SALT_SIZE + NONCE_SIZE :], MAGIC)
    except InvalidTag as exc:
        raise WrongPassword("Senha incorreta ou arquivo danificado.") from exc


def snapshot() -> bytes:
    """Cópia consistente do banco, mesmo com o app gravando ao mesmo tempo."""
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "copia.db"
        source, dest = db.connect(), sqlite3.connect(target)
        try:
            with dest:
                source.backup(dest)
        finally:
            dest.close()
            source.close()
        return target.read_bytes()
