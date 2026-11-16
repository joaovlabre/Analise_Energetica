"""Consulta de consumo específico por linha de produção (energia de `energia_intervalo` x `producao`)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from calculo.kpi import RegistroProducao, consumo_especifico, demanda_media_kw, producao_na_janela
from comum.config import Config, Linha
from comum.periodo import dias_locais
from comum.tempo import para_local


def _iso(dt: datetime) -> str:
    return para_local(dt).isoformat(timespec="seconds")


def consultar(engine: Engine, cfg: Config, linha: Linha, inicio: datetime, fim: datetime, agora: datetime) -> dict:
    EI, D, P = E.energia_intervalo, E.dispositivo, E.producao
    passo_min = cfg.agregacao.intervalo_min
    por_ts: dict[datetime, float] = defaultdict(float)  # kWh da linha por intervalo
    qual_ruim = 0
    flags: set[str] = set()
    motivos: set[str] = set()
    unidade = "kWh"
    medidores = []
    with engine.connect() as con:
        for m in linha.eletricidade:
            disp_id = con.execute(select(D.c.id).where(D.c.nome == m.dispositivo)).scalar()
            medidores.append(dict(dispositivo=m.dispositivo, grandeza=m.grandeza, fator=m.fator, cadastrado=disp_id is not None))
            if disp_id is None:
                continue
            linhas = con.execute(select(EI.c.ts_inicio_utc, EI.c.consumo, EI.c.unidade, EI.c.qualidade, EI.c.flag, EI.c.motivo).where(and_(
                EI.c.dispositivo_id == disp_id, EI.c.grandeza == m.grandeza, EI.c.intervalo_min == passo_min,
                EI.c.ts_inicio_utc >= inicio, EI.c.ts_inicio_utc < fim))).all()
            for l in linhas:
                por_ts[l.ts_inicio_utc] += l.consumo * m.fator
                unidade = l.unidade
                if l.qualidade != "ok":
                    qual_ruim += 1
                if l.flag:
                    flags |= set(l.flag.split(","))
                if l.motivo:
                    motivos.add(l.motivo)
        regs = [RegistroProducao(r.ts_inicio_utc, r.ts_fim_utc, r.quantidade_t) for r in con.execute(
            select(P.c.ts_inicio_utc, P.c.ts_fim_utc, P.c.quantidade_t).where(and_(
                P.c.linha == linha.nome, P.c.ts_fim_utc > inicio, P.c.ts_inicio_utc < fim))).all()]
        origens = set(con.execute(select(P.c.origem).distinct().where(and_(
            P.c.linha == linha.nome, P.c.ts_fim_utc > inicio, P.c.ts_inicio_utc < fim))).scalars())

    energia = sum(por_ts.values())
    producao_t = producao_na_janela(regs, inicio, fim)
    fim_efetivo = min(fim, agora)
    esperados = max(0, int((fim_efetivo - inicio).total_seconds() // (passo_min * 60)))

    dias = []
    for dia, ini, f in dias_locais(inicio, fim):
        e = sum(v for t, v in por_ts.items() if ini <= t < f)
        p = producao_na_janela(regs, ini, f)
        n = sum(1 for t in por_ts if ini <= t < f)
        dias.append(dict(dia=dia.isoformat(), energia=e if n else None, producao_t=p, especifico=consumo_especifico(e if n else None, p), intervalos=n))

    # perfil médio de demanda por horário do dia (kW médio de cada intervalo de 15 min)
    soma_slot: dict[str, list[float]] = defaultdict(list)
    for t, v in por_ts.items():
        soma_slot[para_local(t).strftime("%H:%M")].append(demanda_media_kw(v, passo_min))
    perfil = [dict(hora=h, kw=sum(vs) / len(vs)) for h, vs in sorted(soma_slot.items())]
    demanda_max = max(((t, demanda_media_kw(v, passo_min)) for t, v in por_ts.items()), key=lambda x: x[1], default=None)

    return dict(
        linha=linha.nome, descricao=linha.descricao, medidores=medidores,
        inicio=_iso(inicio), fim=_iso(fim), unidade=unidade,
        energia=energia if por_ts else None, producao_t=producao_t, especifico=consumo_especifico(energia if por_ts else None, producao_t),
        unidade_especifico=f"{unidade}/t",
        intervalos=len(por_ts), intervalos_esperados=esperados,
        cobertura=(len(por_ts) / esperados) if esperados else None,
        intervalos_estimados=qual_ruim, flags=sorted(flags), motivos=sorted(motivos),
        simulado=("simulado" in flags) or ("simulado" in origens), origens_producao=sorted(origens),
        demanda_max_kw=demanda_max[1] if demanda_max else None, demanda_max_em=_iso(demanda_max[0]) if demanda_max else None,
        dias=dias, perfil=perfil,
    )
