from datetime import datetime, timedelta

import pytest
from sqlalchemy import insert, select

from armazenamento import esquema as E
from armazenamento.gravador import gravar_leituras
from armazenamento.agregacao import agregar
from comum.config import Agregacao

T0 = datetime(2026, 11, 13, 12, 0, 0)


@pytest.fixture
def engine(tmp_path):
    eng = E.criar_engine(f"sqlite:///{tmp_path / 't.db'}")
    E.criar_tabelas(eng)
    with eng.begin() as con:
        con.execute(insert(E.dispositivo).values(id=1, nome="M1", modelo="X", origem="modbus_tcp", ativo=True))
    return eng


def _gravar(engine, minutos, valor0=1000.0, inicio=T0, qualidade="ok"):
    gravar_leituras(
        engine,
        [
            dict(ts_utc=inicio + timedelta(minutes=m), dispositivo_id=1, grandeza="energia_ativa_importada",
                 valor=valor0 + m, unidade="kWh", qualidade=qualidade)
            for m in minutos
        ],
    )


def _intervalos(engine):
    with engine.connect() as con:
        return con.execute(select(E.energia_intervalo).order_by(E.energia_intervalo.c.ts_inicio_utc)).all()


def test_agregacao_incremental_e_idempotente(engine):
    cfg = Agregacao(intervalo_min=15, grandezas=["energia_ativa_importada"], max_lacuna_min=5)
    _gravar(engine, range(0, 20))  # 12:00..12:19
    assert agregar(engine, cfg, [1]) == 1
    assert agregar(engine, cfg, [1]) == 0  # nada novo
    _gravar(engine, range(20, 46))  # até 12:45
    assert agregar(engine, cfg, [1]) == 2
    linhas = _intervalos(engine)
    assert [l.ts_inicio_utc.minute for l in linhas] == [0, 15, 30]
    assert [l.consumo for l in linhas] == pytest.approx([15, 15, 15])
    assert all(l.unidade == "kWh" and l.qualidade == "ok" for l in linhas)


def test_lacuna_marcada_estimado(engine):
    cfg = Agregacao(intervalo_min=15, grandezas=["energia_ativa_importada"], max_lacuna_min=5)
    _gravar(engine, list(range(0, 6)) + list(range(40, 61)))
    agregar(engine, cfg, [1])
    linhas = _intervalos(engine)
    assert sum(l.consumo for l in linhas) == pytest.approx(60)
    assert linhas[1].qualidade == "estimado" and "lacuna" in linhas[1].flag


def test_leituras_timeout_ignoradas(engine):
    cfg = Agregacao(intervalo_min=15, grandezas=["energia_ativa_importada"])
    _gravar(engine, range(0, 31), qualidade="timeout")
    assert agregar(engine, cfg, [1]) == 0
