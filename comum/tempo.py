"""Funções de tempo. Regra: gravação sempre em UTC (datetime ingênuo = UTC); exibição em America/Araguaina."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FUSO_EXIBICAO = ZoneInfo("America/Araguaina")


def agora_utc() -> datetime:
    """Instante atual em UTC, sem tzinfo (formato gravado no banco)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def para_utc_ingenuo(dt: datetime) -> datetime:
    """Converte qualquer datetime para UTC ingênuo. Datetime sem tzinfo é tratado como UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def para_local(dt_utc: datetime) -> datetime:
    """UTC ingênuo -> horário local de exibição (com tzinfo)."""
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(FUSO_EXIBICAO)


def inicio_intervalo(dt_utc: datetime, minutos: int = 15) -> datetime:
    """Início do intervalo alinhado ao relógio (:00, :15, :30, :45 para 15 min) que contém dt_utc.

    America/Araguaina tem offset inteiro em horas (UTC-3), então o alinhamento em UTC
    coincide com o alinhamento no horário local.
    """
    if 60 % minutos != 0 and minutos % 60 != 0:
        raise ValueError("intervalo deve dividir a hora (ex.: 1, 5, 15, 30, 60)")
    base = dt_utc.replace(second=0, microsecond=0)
    if minutos >= 60:
        base = base.replace(minute=0)
        horas = minutos // 60
        return base - timedelta(hours=base.hour % horas)
    return base - timedelta(minutes=base.minute % minutos)
