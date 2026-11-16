from datetime import datetime

import pytest

from calculo.kpi import RegistroProducao, consumo_especifico, demanda_media_kw, producao_na_janela


def test_consumo_especifico():
    assert consumo_especifico(124_000, 3780) == pytest.approx(32.804, abs=1e-3)
    assert consumo_especifico(1000, 0) is None
    assert consumo_especifico(None, 10) is None


def test_producao_rateada_pela_sobreposicao():
    regs = [RegistroProducao(datetime(2026, 10, 1, 3), datetime(2026, 10, 2, 3), 120.0)]
    assert producao_na_janela(regs, datetime(2026, 10, 1, 3), datetime(2026, 10, 2, 3)) == pytest.approx(120)
    assert producao_na_janela(regs, datetime(2026, 10, 1, 15), datetime(2026, 10, 5)) == pytest.approx(60)  # metade do dia
    assert producao_na_janela(regs, datetime(2026, 10, 3), datetime(2026, 10, 4)) == 0


def test_demanda_media():
    assert demanda_media_kw(45.0, 15) == pytest.approx(180.0)
