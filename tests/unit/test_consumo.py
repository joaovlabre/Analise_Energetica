from datetime import datetime, timedelta

import pytest

from calculo.consumo import Amostra, calcular_incrementos, distribuir_em_intervalos
from comum.tempo import inicio_intervalo, para_local

T0 = datetime(2026, 11, 13, 12, 0, 0)  # UTC


def serie(valores_por_minuto, inicio=T0, passo_s=60):
    return [Amostra(inicio + timedelta(seconds=i * passo_s), v) for i, v in enumerate(valores_por_minuto)]


def test_alinhamento_15min():
    assert inicio_intervalo(datetime(2026, 1, 1, 10, 14, 59)) == datetime(2026, 1, 1, 10, 0)
    assert inicio_intervalo(datetime(2026, 1, 1, 10, 15, 0)) == datetime(2026, 1, 1, 10, 15)
    assert inicio_intervalo(datetime(2026, 1, 1, 10, 59, 1), 60) == datetime(2026, 1, 1, 10, 0)


def test_fuso_araguaina():
    assert para_local(datetime(2026, 1, 1, 15, 0)).hour == 12  # UTC-3, sem horário de verão


def test_consumo_constante_um_intervalo():
    # 1 kWh por minuto, de 12:00 a 12:30 -> dois intervalos de 15 kWh
    amostras = serie([1000 + i for i in range(31)])
    res = distribuir_em_intervalos(calcular_incrementos(amostras, max_lacuna_s=300))
    assert [r.inicio for r in res] == [T0, T0 + timedelta(minutes=15)]
    assert [r.consumo for r in res] == pytest.approx([15, 15])
    assert all(r.qualidade == "ok" for r in res)


def test_intervalo_aberto_nao_e_emitido():
    amostras = serie([1000 + i for i in range(20)])  # até 12:19
    res = distribuir_em_intervalos(calcular_incrementos(amostras, max_lacuna_s=300))
    assert len(res) == 1 and res[0].inicio == T0


def test_amostras_desalinhadas_interpolam_na_fronteira():
    # 12:14:30 -> 12:15:30 o totalizador avança 10 kWh: a fronteira 12:15 cai no meio do incremento
    amostras = [Amostra(T0 - timedelta(seconds=30), 0), Amostra(T0 + timedelta(minutes=14, seconds=30), 0), Amostra(T0 + timedelta(minutes=15, seconds=30), 10)]
    res = distribuir_em_intervalos(calcular_incrementos(amostras, max_lacuna_s=3600))
    primeiro = next(r for r in res if r.inicio == T0)
    assert primeiro.consumo == pytest.approx(5)  # metade dos 10 kWh antes de 12:15


def test_reset_nao_gera_negativo():
    amostras = serie([500, 501, 502, 0, 1, 2] + [2 + i for i in range(1, 30)])
    incs = calcular_incrementos(amostras, max_lacuna_s=300)
    assert all(i.delta >= 0 for i in incs)
    assert any("reset" in i.flags for i in incs)
    res = distribuir_em_intervalos(incs)
    assert all(r.consumo >= 0 for r in res)
    assert res[0].qualidade == "estimado" and "reset" in res[0].flags


def test_rollover_conhecido():
    amostras = [Amostra(T0, 99_990), Amostra(T0 + timedelta(minutes=1), 5)]
    (inc,) = calcular_incrementos(amostras, max_lacuna_s=300, limite_rollover=100_000)
    assert inc.delta == pytest.approx(15) and "rollover" in inc.flags


def test_troca_de_medidor_com_valor_alto_nao_gera_pico():
    # medidor novo começa em 50.000: sem limite de plausibilidade seria um pico falso
    amostras = [Amostra(T0, 1000), Amostra(T0 + timedelta(minutes=1), 1001), Amostra(T0 + timedelta(minutes=2), 50_000)]
    incs = calcular_incrementos(amostras, max_lacuna_s=300, max_por_hora=500)
    assert incs[1].delta == 0 and "pico_suspeito" in incs[1].flags


def test_lacuna_recuperada_pela_diferenca():
    # comunicação cai de 12:05 a 12:50; o totalizador avançou 45 kWh no período
    amostras = serie([1000 + i for i in range(6)])  # 12:00..12:05
    amostras += serie([1050 + i for i in range(11)], inicio=T0 + timedelta(minutes=50))  # 12:50..13:00
    res = distribuir_em_intervalos(calcular_incrementos(amostras, max_lacuna_s=300))
    assert [r.inicio.minute for r in res] == [0, 15, 30, 45]
    assert sum(r.consumo for r in res) == pytest.approx(1060 - 1000)  # total conservado
    assert all(r.qualidade == "estimado" for r in res)
    assert "lacuna" in res[1].flags


def test_primeiro_intervalo_incompleto():
    amostras = serie([1000 + i for i in range(30)], inicio=T0 + timedelta(minutes=5))  # 12:05..12:34
    res = distribuir_em_intervalos(calcular_incrementos(amostras, max_lacuna_s=300))
    assert "incompleto" in res[0].flags
    assert res[1].qualidade == "ok"
