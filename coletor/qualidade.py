"""Marcação de qualidade: valores fora da faixa física são gravados com 'fora_faixa', nunca descartados."""
from __future__ import annotations

import math

from comum.config import Faixa

OK = "ok"
TIMEOUT = "timeout"
FORA_FAIXA = "fora_faixa"
ESTIMADO = "estimado"
MANUAL = "manual"


def faixa_para(grandeza: str, faixas: dict[str, Faixa]) -> Faixa | None:
    """Faixa cujo prefixo casa com a grandeza (o prefixo mais longo vence)."""
    candidatos = [p for p in faixas if grandeza.startswith(p)]
    return faixas[max(candidatos, key=len)] if candidatos else None


def avaliar(grandeza: str, valor: float | None, faixas: dict[str, Faixa]) -> tuple[float | None, str]:
    """Retorna (valor_para_gravar, qualidade). NaN/inf viram None com 'fora_faixa'."""
    if valor is None or not math.isfinite(valor):
        return None, FORA_FAIXA
    faixa = faixa_para(grandeza, faixas)
    if faixa and not (faixa.minimo <= valor <= faixa.maximo):
        return valor, FORA_FAIXA
    return valor, OK
