"""Abre um backup baixado do Telegram.  Uso: python -m forca.restore arquivo.forca saida.db"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from .backup import WrongPassword, decrypt


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    target = Path(sys.argv[2])
    if target.exists():
        print(f"{target} já existe; escolha outro nome.")
        return 1
    try:
        data = decrypt(Path(sys.argv[1]).read_bytes(), getpass.getpass("Senha do app: "))
    except WrongPassword as exc:
        print(exc)
        return 1
    target.write_bytes(data)
    print(f"Pronto: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
