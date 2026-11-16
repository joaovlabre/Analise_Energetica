from datetime import date, datetime

import pytest

from comum.periodo import dias_locais, resolver_periodo

# 16/11/2026 12:00 em Araguaína (UTC-3) = 15:00 UTC
AGORA = datetime(2026, 11, 16, 15, 0)


def test_mes_anterior_em_horario_local():
    assert resolver_periodo("mes_anterior", AGORA) == (datetime(2026, 10, 1, 3), datetime(2026, 11, 1, 3))


def test_mes_anterior_em_janeiro_volta_o_ano():
    assert resolver_periodo("mes_anterior", datetime(2027, 1, 10, 12)) == (datetime(2026, 12, 1, 3), datetime(2027, 1, 1, 3))


def test_hoje_comeca_a_meia_noite_local():
    # 01:00 UTC de 17/11 ainda é 16/11 em Araguaína (22:00)
    ini, fim = resolver_periodo("hoje", datetime(2026, 11, 17, 1, 0))
    assert ini == datetime(2026, 11, 16, 3) and fim == datetime(2026, 11, 17, 1)


def test_ontem_e_personalizado():
    assert resolver_periodo("ontem", AGORA) == (datetime(2026, 11, 15, 3), datetime(2026, 11, 16, 3))
    assert resolver_periodo("personalizado", AGORA, date(2026, 10, 5), date(2026, 10, 5)) == (datetime(2026, 10, 5, 3), datetime(2026, 10, 6, 3))
    with pytest.raises(ValueError):
        resolver_periodo("personalizado", AGORA, date(2026, 10, 6), date(2026, 10, 5))
    with pytest.raises(ValueError):
        resolver_periodo("semana_que_vem", AGORA)


def test_dias_locais_cobrem_o_mes():
    dias = dias_locais(*resolver_periodo("mes_anterior", AGORA))
    assert len(dias) == 31 and dias[0][0] == date(2026, 10, 1) and dias[-1][0] == date(2026, 10, 31)
    assert dias[0][1] == datetime(2026, 10, 1, 3) and dias[-1][2] == datetime(2026, 11, 1, 3)
