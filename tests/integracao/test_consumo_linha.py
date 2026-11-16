"""Consumo específico por linha: simulação de um mês (3.780 t) -> energia_intervalo/producao -> API."""
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.app import criar_app
from armazenamento import esquema as E
from comum.config import carregar_config
from ferramentas.simular_producao import ErroSimulacao, simular

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def ambiente(tmp_path):
    cfg = carregar_config(RAIZ / "config/dispositivos.simulador.yaml")
    cfg.banco.url = f"sqlite:///{(tmp_path / 'sge_simulador.db').as_posix()}"
    engine = E.criar_engine(cfg.banco.url)
    E.criar_tabelas(engine)
    return cfg, engine


def test_simulacao_e_api(ambiente, monkeypatch):
    cfg, engine = ambiente
    r = simular(engine, cfg, "Linha 1", 3780, 2026, 10)
    assert r["dias"] == 31 and r["intervalos"] == 31 * 96
    assert r["producao_t"] == pytest.approx(3780, abs=1e-6)
    assert r["soma_intervalos_kwh"] == pytest.approx(r["energia_kwh"], abs=0.01)  # intervalos = diferença do totalizador
    assert 30 <= r["kwh_por_t"] <= 35
    with engine.connect() as con:
        assert con.execute(select(func.sum(E.producao.c.quantidade_t))).scalar() == pytest.approx(3780)
        flags = set(con.execute(select(E.energia_intervalo.c.flag).distinct()).scalars())
    assert flags == {"simulado"}

    with pytest.raises(ErroSimulacao):  # idempotente: não grava duas vezes
        simular(engine, cfg, "Linha 1", 3780, 2026, 10)

    import api.app as modulo
    monkeypatch.setattr(modulo, "agora_utc", lambda: datetime(2026, 11, 16, 15, 0))
    cliente = TestClient(criar_app(cfg, engine))
    assert cliente.get("/api/linhas").json()[0]["nome"] == "Linha 1"
    k = cliente.get("/api/consumo_especifico", params={"linha": "Linha 1", "periodo": "mes_anterior"}).json()
    assert k["producao_t"] == pytest.approx(3780)
    assert k["energia"] == pytest.approx(r["energia_kwh"], abs=0.01)
    assert k["especifico"] == pytest.approx(r["kwh_por_t"], rel=1e-6)
    assert k["simulado"] and k["cobertura"] == pytest.approx(1.0)
    assert len(k["dias"]) == 31 and sum(d["producao_t"] for d in k["dias"]) == pytest.approx(3780)
    perfil = {p["hora"]: p["kw"] for p in k["perfil"]}
    assert len(perfil) == 96
    ponta = sum(perfil[h] for h in perfil if "18:00" <= h < "21:00") / 12
    fora = sum(perfil[h] for h in perfil if h < "18:00") / 72
    assert ponta < 0.5 * fora  # demanda cai bastante na ponta
    dia = cliente.get("/api/consumo_especifico", params={"linha": "Linha 1", "periodo": "personalizado", "inicio": "2026-10-05", "fim": "2026-10-05"}).json()
    assert dia["intervalos"] == 96 and dia["producao_t"] == pytest.approx(k["dias"][4]["producao_t"])
    assert cliente.get("/api/consumo_especifico", params={"linha": "Linha 9"}).status_code == 404
    assert cliente.get("/api/consumo_especifico", params={"linha": "Linha 1", "periodo": "xyz"}).status_code == 422
    for pagina in ("/paineis", "/paineis/consumo-linha", "/paineis/visao-geral", "/diagramas", "/alarmes", "/"):
        resp = cliente.get(pagina)
        assert resp.status_code == 200 and "SGE" in resp.text
    assert cliente.get("/paineis/nao-existe").status_code == 404


def test_simulacao_recusa_banco_que_nao_e_do_simulador(ambiente, tmp_path):
    cfg, _ = ambiente
    cfg.banco.url = f"sqlite:///{(tmp_path / 'producao.db').as_posix()}"
    with pytest.raises(ErroSimulacao):
        simular(E.criar_engine(cfg.banco.url), cfg, "Linha 1", 3780, 2026, 10)
