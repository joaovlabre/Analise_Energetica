"""KPIs de consumo específico (funções puras).

Consumo vem sempre de energia por intervalo (diferença de totalizador), nunca de integração de kW.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RegistroProducao:
    inicio: datetime
    fim: datetime
    quantidade_t: float


def consumo_especifico(energia: float | None, producao_t: float | None) -> float | None:
    """Energia por tonelada (ex.: kWh/t). Sem produção (ou sem energia) não há indicador: devolve None."""
    if energia is None or not producao_t or producao_t <= 0:
        return None
    return energia / producao_t


def producao_na_janela(registros: list[RegistroProducao], inicio: datetime, fim: datetime) -> float:
    """Toneladas produzidas em [inicio, fim). Registro que cruza a janela entra proporcional à sobreposição."""
    total = 0.0
    for r in registros:
        dur = (r.fim - r.inicio).total_seconds()
        if dur <= 0:
            if inicio <= r.inicio < fim:
                total += r.quantidade_t
            continue
        sobre = (min(r.fim, fim) - max(r.inicio, inicio)).total_seconds()
        if sobre > 0:
            total += r.quantidade_t * sobre / dur
    return total


def demanda_media_kw(consumo_kwh: float, intervalo_min: int) -> float:
    """Demanda média do intervalo a partir da energia do intervalo (kWh -> kW)."""
    return consumo_kwh * 60.0 / intervalo_min
