"""Energia por intervalo (15 min) a partir do totalizador gravado em `leitura`.

Idempotente: só calcula intervalos posteriores ao último já gravado e nunca reescreve.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from calculo.consumo import Amostra, calcular_incrementos, distribuir_em_intervalos
from comum.config import Agregacao
from comum.tempo import agora_utc, inicio_intervalo

log = logging.getLogger("armazenamento.agregacao")

QUALIDADES_VALIDAS = ("ok", "fora_faixa", "estimado", "manual")


def _amostras(con, disp_id: int, grandeza: str, desde: datetime | None) -> tuple[list[Amostra], str | None]:
    L = E.leitura
    base = (L.c.dispositivo_id == disp_id) & (L.c.grandeza == grandeza) & L.c.valor.is_not(None) & L.c.qualidade.in_(QUALIDADES_VALIDAS)
    linhas = []
    if desde is not None:
        anterior = con.execute(
            select(L.c.ts_utc, L.c.valor, L.c.unidade).where(base, L.c.ts_utc <= desde).order_by(L.c.ts_utc.desc()).limit(1)
        ).first()
        if anterior:
            linhas.append(anterior)
        q = select(L.c.ts_utc, L.c.valor, L.c.unidade).where(base, L.c.ts_utc > desde)
    else:
        q = select(L.c.ts_utc, L.c.valor, L.c.unidade).where(base)
    linhas.extend(con.execute(q.order_by(L.c.ts_utc)).all())
    unidade = linhas[-1].unidade if linhas else None
    return [Amostra(r.ts_utc, r.valor) for r in linhas], unidade


def agregar(engine: Engine, cfg: Agregacao, dispositivo_ids: list[int], agora: datetime | None = None) -> int:
    """Calcula e grava os intervalos fechados ainda não gravados. Retorna quantos foram inseridos."""
    agora = agora or agora_utc()
    passo = timedelta(minutes=cfg.intervalo_min)
    EI = E.energia_intervalo
    novos = 0
    for disp_id in dispositivo_ids:
        for grandeza in cfg.grandezas:
            with engine.begin() as con:
                ultimo = con.execute(
                    select(func.max(EI.c.ts_inicio_utc)).where(
                        EI.c.dispositivo_id == disp_id, EI.c.grandeza == grandeza, EI.c.intervalo_min == cfg.intervalo_min
                    )
                ).scalar()
                desde = ultimo + passo if ultimo else None
                amostras, unidade = _amostras(con, disp_id, grandeza, desde)
                if len(amostras) < 2:
                    continue
                incs = calcular_incrementos(amostras, max_lacuna_s=cfg.max_lacuna_min * 60)
                intervalos = distribuir_em_intervalos(incs, cfg.intervalo_min)
                limite = desde if desde is not None else inicio_intervalo(amostras[0].ts, cfg.intervalo_min)
                linhas = [
                    dict(
                        ts_inicio_utc=ci.inicio,
                        intervalo_min=cfg.intervalo_min,
                        dispositivo_id=disp_id,
                        grandeza=grandeza,
                        consumo=round(ci.consumo, 6),
                        unidade=unidade,
                        qualidade=ci.qualidade,
                        flag=",".join(sorted(ci.flags)) or None,
                        motivo=ci.motivo or None,
                        ts_calculo_utc=agora,
                    )
                    for ci in intervalos
                    if ci.inicio >= limite
                ]
                if linhas:
                    con.execute(insert(EI), linhas)
                    novos += len(linhas)
                    log.info("disp %s %s: %d intervalo(s) de %d min gravado(s)", disp_id, grandeza, len(linhas), cfg.intervalo_min)
    return novos
