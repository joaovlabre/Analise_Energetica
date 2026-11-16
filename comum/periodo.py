"""Períodos de consulta (função pura). Limites de dia e mês no horário de exibição (America/Araguaina).

Devolve sempre (inicio, fim) em UTC ingênuo, com fim exclusivo.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from comum.tempo import FUSO_EXIBICAO, para_local, para_utc_ingenuo

TIPOS = ("ultima_hora", "24h", "7d", "30d", "hoje", "ontem", "este_mes", "mes_anterior", "personalizado")


def meia_noite_utc(dia: date) -> datetime:
    """00:00 local do dia -> UTC ingênuo."""
    return para_utc_ingenuo(datetime.combine(dia, time(0), tzinfo=FUSO_EXIBICAO))


def resolver_periodo(tipo: str, agora_utc: datetime, inicio: date | None = None, fim: date | None = None) -> tuple[datetime, datetime]:
    """`personalizado` usa as datas locais `inicio` e `fim` (fim inclusive: vai até 24:00 do dia `fim`)."""
    hoje = para_local(agora_utc).date()
    if tipo == "ultima_hora":
        return agora_utc - timedelta(hours=1), agora_utc
    if tipo == "24h":
        return agora_utc - timedelta(hours=24), agora_utc
    if tipo == "7d":
        return agora_utc - timedelta(days=7), agora_utc
    if tipo == "30d":
        return agora_utc - timedelta(days=30), agora_utc
    if tipo == "hoje":
        return meia_noite_utc(hoje), agora_utc
    if tipo == "ontem":
        return meia_noite_utc(hoje - timedelta(days=1)), meia_noite_utc(hoje)
    primeiro = hoje.replace(day=1)
    if tipo == "este_mes":
        return meia_noite_utc(primeiro), agora_utc
    if tipo == "mes_anterior":
        anterior = (primeiro - timedelta(days=1)).replace(day=1)
        return meia_noite_utc(anterior), meia_noite_utc(primeiro)
    if tipo == "personalizado":
        if inicio is None or fim is None:
            raise ValueError("período personalizado exige início e fim")
        if fim < inicio:
            raise ValueError("fim anterior ao início")
        return meia_noite_utc(inicio), meia_noite_utc(fim + timedelta(days=1))
    raise ValueError(f"período desconhecido: {tipo}")


def dias_locais(inicio_utc: datetime, fim_utc: datetime) -> list[tuple[date, datetime, datetime]]:
    """Dias locais que cobrem [inicio, fim): (data, inicio_utc do trecho, fim_utc do trecho)."""
    saida = []
    dia = para_local(inicio_utc).date()
    while True:
        ini = max(meia_noite_utc(dia), inicio_utc)
        fim = min(meia_noite_utc(dia + timedelta(days=1)), fim_utc)
        if ini >= fim_utc:
            break
        if fim > ini:
            saida.append((dia, ini, fim))
        dia += timedelta(days=1)
    return saida
