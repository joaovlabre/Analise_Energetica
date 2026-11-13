"""Configuração de log: console + arquivo rotativo em logs/."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configurar_log(nome_arquivo: str = "sge.log", debug: bool = False, pasta: str | Path = "logs") -> None:
    nivel = logging.DEBUG if debug else logging.INFO
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)

    for fluxo in (sys.stdout, sys.stderr):  # console do Windows: acentos corretos
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz.addHandler(console)

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = RotatingFileHandler(pasta / nome_arquivo, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)

    # pymodbus é verboso (e anexa dumps de quadros aos erros); o coletor loga TX/RX e falhas por conta própria
    for nome in ("pymodbus", "pymodbus.logging"):
        logging.getLogger(nome).setLevel(logging.CRITICAL)
