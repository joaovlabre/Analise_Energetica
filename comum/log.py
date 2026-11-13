"""Configuração de log: console + arquivo rotativo em logs/."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configurar_log(nome_arquivo: str = "sge.log", debug: bool = False, pasta: str | Path = "logs") -> None:
    nivel = logging.DEBUG if debug else logging.INFO
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz.addHandler(console)

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = RotatingFileHandler(pasta / nome_arquivo, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)

    # pymodbus é muito verboso em DEBUG; só mostramos o que nós mesmos logamos
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
