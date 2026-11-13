"""Consumo a partir de totalizadores acumulados (funções puras).

Regras (CLAUDE.md):
- Consumo de um período = diferença entre leituras do totalizador (nunca integrar kW).
- Reset/troca de medidor nunca gera consumo negativo nem pico falso.
- Lacuna de comunicação: o consumo é recuperado pela diferença quando a comunicação volta,
  distribuído no tempo e marcado como 'estimado'.

Cada par de amostras consecutivas vira um "incremento" (t0, t1, delta). O delta é
distribuído uniformemente no tempo entre t0 e t1 (equivale a interpolar linearmente o
totalizador nas fronteiras dos intervalos de 15 min). Assim o total é conservado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from comum.tempo import inicio_intervalo


@dataclass(frozen=True)
class Amostra:
    ts: datetime
    valor: float


@dataclass
class Incremento:
    t0: datetime
    t1: datetime
    delta: float
    flags: set[str] = field(default_factory=set)


@dataclass
class ConsumoIntervalo:
    inicio: datetime
    consumo: float = 0.0
    cobertura_s: float = 0.0
    flags: set[str] = field(default_factory=set)

    @property
    def qualidade(self) -> str:
        return "estimado" if self.flags else "ok"

    @property
    def motivo(self) -> str:
        textos = {
            "lacuna": "lacuna de comunicação: consumo recuperado pela diferença do totalizador e distribuído no tempo",
            "reset": "totalizador diminuiu (reset ou troca de medidor): trecho considerado zero",
            "rollover": "estouro (rollover) do totalizador tratado",
            "pico_suspeito": "incremento acima do máximo plausível: trecho considerado zero",
            "incompleto": "intervalo sem cobertura completa de leituras",
        }
        return "; ".join(textos[f] for f in sorted(self.flags) if f in textos)


def calcular_incrementos(
    amostras: list[Amostra],
    max_lacuna_s: float,
    limite_rollover: float | None = None,
    max_por_hora: float | None = None,
) -> list[Incremento]:
    """Diferenças entre amostras consecutivas, com tratamento de reset/rollover/lacuna.

    - `limite_rollover`: valor em que o totalizador volta a zero (se conhecido).
    - `max_por_hora`: consumo máximo plausível por hora (ex.: potência instalada); acima disso o
      trecho é considerado suspeito e zerado (com flag), em vez de gerar um pico falso.
    """
    ordenadas = sorted((a for a in amostras if a.valor is not None), key=lambda a: a.ts)
    saida: list[Incremento] = []
    for a, b in zip(ordenadas, ordenadas[1:]):
        dt = (b.ts - a.ts).total_seconds()
        if dt <= 0:
            continue
        flags: set[str] = set()
        delta = b.valor - a.valor
        if delta < 0:
            if limite_rollover is not None and a.valor >= 0.9 * limite_rollover and b.valor <= 0.1 * limite_rollover:
                delta = (limite_rollover - a.valor) + b.valor
                flags.add("rollover")
            else:
                delta = 0.0
                flags.add("reset")
        if max_por_hora is not None and delta > max_por_hora * dt / 3600.0 * 1.05 + 1e-9:
            delta = 0.0
            flags.add("pico_suspeito")
        if dt > max_lacuna_s:
            flags.add("lacuna")
        saida.append(Incremento(a.ts, b.ts, delta, flags))
    return saida


def distribuir_em_intervalos(incrementos: list[Incremento], intervalo_min: int = 15) -> list[ConsumoIntervalo]:
    """Distribui os incrementos em intervalos alinhados ao relógio.

    Só devolve intervalos **fechados**: cujo fim é ≤ ao último instante coberto pelas amostras.
    """
    if not incrementos:
        return []
    passo = timedelta(minutes=intervalo_min)
    duracao_s = passo.total_seconds()
    intervalos: dict[datetime, ConsumoIntervalo] = {}
    for inc in incrementos:
        total_s = (inc.t1 - inc.t0).total_seconds()
        ini = inicio_intervalo(inc.t0, intervalo_min)
        while ini < inc.t1:
            fim = ini + passo
            sobre = (min(fim, inc.t1) - max(ini, inc.t0)).total_seconds()
            if sobre > 0:
                ci = intervalos.setdefault(ini, ConsumoIntervalo(inicio=ini))
                ci.consumo += inc.delta * sobre / total_s
                ci.cobertura_s += sobre
                ci.flags |= inc.flags
            ini = fim
    ultimo = max(i.t1 for i in incrementos)
    fechados = []
    for ini in sorted(intervalos):
        ci = intervalos[ini]
        if ini + passo > ultimo:
            continue
        if ci.cobertura_s < duracao_s - 1e-6:
            ci.flags.add("incompleto")
        fechados.append(ci)
    return fechados
