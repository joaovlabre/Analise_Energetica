"""Gera um mês SIMULADO de produção e consumo para uma linha (só no banco do simulador).

Perfil (semente fixa, reprodutível):
  - 3 turnos todos os dias, inclusive domingo (produção 24 h);
  - horário de ponta (18h às 21h, horário local): cargas de produção reduzidas a ~20-25 %;
  - carga de base sempre ligada; ruído por intervalo e variação por dia;
  - leituras do totalizador a cada 1 min, como o coletor.

O consumo NÃO é gravado direto: são gravadas leituras do totalizador (a cada 15 min) e os intervalos
são calculados a partir delas pelas mesmas funções da agregação (calculo/consumo.py), com flag 'simulado'.
A produção do mês é rateada pelos dias proporcionalmente à energia de produção e gravada em `producao`
com origem 'simulado'.

  python -m ferramentas.simular_producao --config config/dispositivos.simulador.yaml --linha "Linha 1" --toneladas 3780 --mes 2026-10
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, insert, select
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from armazenamento.gravador import ids_pontos, sincronizar_dispositivos
from calculo.consumo import Amostra, calcular_incrementos, distribuir_em_intervalos
from comum.config import Config, carregar_config, carregar_hierarquia, url_sem_senha
from comum.periodo import dias_locais, meia_noite_utc
from comum.tempo import agora_utc, para_local

MOTIVO = "dados simulados (ferramentas.simular_producao)"


class ErroSimulacao(Exception):
    pass


@dataclass
class Perfil:
    base_kw: float = 40.0
    producao_kw: float = 140.0
    ponta_inicio_h: int = 18
    ponta_fim_h: int = 21
    fator_ponta: tuple[float, float] = (0.18, 0.25)
    ruido: float = 0.06
    variacao_diaria: tuple[float, float] = (0.92, 1.05)


def gerar_intervalos(inicio_utc: datetime, fim_utc: datetime, perfil: Perfil, semente: int) -> list[tuple[datetime, float, float]]:
    """[(inicio_utc, kWh total, kWh de produção)] de 15 em 15 min."""
    rnd = random.Random(semente)
    saida = []
    fator_dia: dict[date, float] = {}
    t = inicio_utc
    while t < fim_utc:
        local = para_local(t)
        f_dia = fator_dia.setdefault(local.date(), rnd.uniform(*perfil.variacao_diaria))
        if perfil.ponta_inicio_h <= local.hour < perfil.ponta_fim_h:
            f_prod = rnd.uniform(*perfil.fator_ponta)
        else:
            f_prod = f_dia * (1 + rnd.uniform(-perfil.ruido, perfil.ruido))
        prod_kw = perfil.producao_kw * f_prod
        base_kw = perfil.base_kw * (1 + rnd.uniform(-0.03, 0.03))
        saida.append((t, (prod_kw + base_kw) / 4, prod_kw / 4))
        t += timedelta(minutes=15)
    return saida


def simular(engine: Engine, cfg: Config, linha: str, toneladas: float, ano: int, mes: int,
            semente: int = 3780, totalizador_inicial: float = 500_000.0, perfil: Perfil | None = None) -> dict:
    if "simulador" not in cfg.banco.url:
        raise ErroSimulacao(f"recusado: o banco '{url_sem_senha(cfg.banco.url)}' não é do simulador (a URL precisa conter 'simulador')")
    hier = carregar_hierarquia(cfg)
    lin = hier.linha(linha)
    if len(lin.eletricidade) != 1:
        raise ErroSimulacao("a simulação suporta linhas com exatamente um medidor elétrico")
    med = lin.eletricidade[0]
    E.criar_tabelas(engine)
    disp_id = sincronizar_dispositivos(engine, cfg)[med.dispositivo]

    inicio = meia_noite_utc(date(ano, mes, 1))
    prox = date(ano + (mes == 12), mes % 12 + 1, 1)
    fim = meia_noite_utc(prox)
    L, EI, P = E.leitura, E.energia_intervalo, E.producao
    with engine.connect() as con:
        ja = con.execute(select(func.count()).select_from(P).where(and_(
            P.c.linha == linha, P.c.origem == "simulado", P.c.ts_inicio_utc >= inicio, P.c.ts_inicio_utc < fim))).scalar()
        ja += con.execute(select(func.count()).select_from(L.join(E.ponto, E.ponto.c.id == L.c.ponto_id)).where(and_(
            E.ponto.c.dispositivo_id == disp_id, E.ponto.c.grandeza == med.grandeza, L.c.ts_utc >= inicio, L.c.ts_utc <= fim))).scalar()
    if ja:
        raise ErroSimulacao(f"já existem dados de {mes:02d}/{ano} para '{linha}' / {med.dispositivo}; nada foi gravado")

    perfil = perfil or Perfil()
    intervalos = gerar_intervalos(inicio, fim, perfil, semente)

    # 1) leituras do totalizador a cada minuto (como o coletor grava o grupo 'energia')
    acumulado = totalizador_inicial
    leituras = [dict(ts_utc=inicio, valor=round(acumulado, 3))]
    for t, kwh, _ in intervalos:
        for minuto in range(1, 16):
            acumulado += kwh / 15
            leituras.append(dict(ts_utc=t + timedelta(minutes=minuto), valor=round(acumulado, 3)))
    # 2) intervalos calculados a partir do totalizador (mesma regra da agregação)
    incs = calcular_incrementos([Amostra(l["ts_utc"], l["valor"]) for l in leituras], max_lacuna_s=cfg.agregacao.max_lacuna_min * 60)
    calc = distribuir_em_intervalos(incs, cfg.agregacao.intervalo_min)
    # 3) produção diária proporcional à energia de produção
    prod_dia: dict[date, float] = {}
    for t, _, kwh_prod in intervalos:
        d = para_local(t).date()
        prod_dia[d] = prod_dia.get(d, 0.0) + kwh_prod
    soma = sum(prod_dia.values())
    dias = dias_locais(inicio, fim)
    t_dia = [round(toneladas * prod_dia[d] / soma, 2) for d, _, _ in dias]
    t_dia[-1] = round(toneladas - sum(t_dia[:-1]), 2)  # fecha exatamente o total

    agora = agora_utc()
    pid = ids_pontos(engine, {(disp_id, med.grandeza, "kWh")})[(disp_id, med.grandeza, "kWh")]
    with engine.begin() as con:
        con.execute(insert(L), [dict(ponto_id=pid, ts_utc=l["ts_utc"], valor=l["valor"], qualidade="ok") for l in leituras])
        con.execute(insert(EI), [dict(
            ts_inicio_utc=ci.inicio, intervalo_min=cfg.agregacao.intervalo_min, dispositivo_id=disp_id, grandeza=med.grandeza,
            consumo=round(ci.consumo, 6), unidade="kWh", qualidade=ci.qualidade, flag=",".join(sorted(ci.flags | {"simulado"})),
            motivo="; ".join(filter(None, [MOTIVO, ci.motivo])), ts_calculo_utc=agora) for ci in calc])
        con.execute(insert(P), [dict(
            ts_inicio_utc=ini, ts_fim_utc=f, linha=linha, produto="Ração (simulada)", quantidade_t=t, origem="simulado",
            usuario="simulador", obs=MOTIVO, ts_registro_utc=agora) for (_, ini, f), t in zip(dias, t_dia)])

    energia = leituras[-1]["valor"] - leituras[0]["valor"]
    return dict(linha=linha, dispositivo=med.dispositivo, inicio=inicio, fim=fim, energia_kwh=energia,
                soma_intervalos_kwh=sum(ci.consumo for ci in calc), producao_t=sum(t_dia),
                kwh_por_t=energia / toneladas, intervalos=len(calc), dias=len(dias))


def main() -> None:
    ap = argparse.ArgumentParser(description="Simula um mês de produção e consumo de uma linha (banco do simulador)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--linha", required=True)
    ap.add_argument("--toneladas", type=float, required=True)
    ap.add_argument("--mes", required=True, help="AAAA-MM")
    ap.add_argument("--semente", type=int, default=3780)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    ano, mes = map(int, args.mes.split("-"))
    cfg = carregar_config(args.config)
    try:
        r = simular(E.criar_engine(cfg.banco.url), cfg, args.linha, args.toneladas, ano, mes, semente=args.semente)
    except (ErroSimulacao, KeyError) as e:
        raise SystemExit(f"ERRO: {e}")
    num = lambda v, c=1: f"{v:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    print(f"{r['linha']} ({r['dispositivo']}), {mes:02d}/{ano}: {r['dias']} dias, {r['intervalos']} intervalos de 15 min")
    print(f"  energia (totalizador): {num(r['energia_kwh'])} kWh  (soma dos intervalos: {num(r['soma_intervalos_kwh'])} kWh)")
    print(f"  ração produzida:       {num(r['producao_t'], 2)} t")
    print(f"  consumo específico:    {num(r['kwh_por_t'], 2)} kWh/t")


if __name__ == "__main__":
    main()
