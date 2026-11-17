import math

from coletor import qualidade as Q
from comum.config import Faixa

FAIXAS = {"tensao_": Faixa(minimo=0, maximo=600)}


def test_nan_vira_none_fora_faixa():
    assert Q.avaliar("potencia_ativa_total", math.nan, FAIXAS) == (None, Q.FORA_FAIXA)


def test_fora_da_faixa_mantem_valor():
    assert Q.avaliar("tensao_an", 700.0, FAIXAS) == (700.0, Q.FORA_FAIXA)


def test_totalizador_negativo_vira_none():
    # EM3261 sem carga: FFFF FFFF FFFF FFFF (INT64 -1) x 0,001 = -0,001 kWh
    assert Q.avaliar("energia_ativa_importada", -0.001, FAIXAS, "energia") == (None, Q.FORA_FAIXA)


def test_totalizador_valido():
    assert Q.avaliar("energia_ativa_importada", 0.0, FAIXAS, "energia") == (0.0, Q.OK)
    assert Q.avaliar("energia_aparente", 0.531, FAIXAS, "energia") == (0.531, Q.OK)


def test_negativo_fora_do_grupo_energia_segue_ok():
    assert Q.avaliar("potencia_ativa_total", -1.5, FAIXAS, "instantaneo") == (-1.5, Q.OK)
