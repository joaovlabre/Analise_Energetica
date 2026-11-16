"""Diagrama unifilar definido em YAML + valores ao vivo em lote."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from api.app import criar_app
from armazenamento import esquema as E
from armazenamento.gravador import sincronizar_dispositivos
from comum.config import carregar_config
from comum.diagramas import carregar_diagramas
from comum.tempo import agora_utc

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def cliente(tmp_path):
    cfg = carregar_config(RAIZ / "config/dispositivos.simulador.yaml")
    cfg.banco.url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    engine = E.criar_engine(cfg.banco.url)
    E.criar_tabelas(engine)
    ids = sincronizar_dispositivos(engine, cfg)
    agora = agora_utc()
    with engine.begin() as con:
        con.execute(insert(E.valor_atual), [
            dict(dispositivo_id=ids["SIM_SCH_EM3261"], grandeza="potencia_ativa_total", ts_utc=agora, valor=123.4, unidade="kW", qualidade="ok", grupo="instantaneo"),
            dict(dispositivo_id=ids["SIM_WEG_MMW02"], grandeza="potencia_ativa_total", ts_utc=agora, valor=456.7, unidade="kW", qualidade="timeout", grupo="instantaneo"),
        ])
        con.execute(insert(E.estado_comunicacao), [
            dict(dispositivo_id=ids["SIM_SCH_EM3261"], online=True, ts_ultima_ok_utc=agora, ts_atualizacao_utc=agora, pedidos_ok=1, pedidos_falha=0),
            dict(dispositivo_id=ids["SIM_WEG_MMW02"], online=False, ts_ultima_ok_utc=None, ts_atualizacao_utc=agora, pedidos_ok=0, pedidos_falha=1),
        ])
    return TestClient(criar_app(cfg, engine)), ids, cfg


def test_unifilar_geral(cliente):
    c, ids, cfg = cliente
    assert [d["slug"] for d in c.get("/api/diagramas").json()] == ["unifilar-geral"]
    d = c.get("/api/diagramas/unifilar-geral").json()
    assert d["barra"]["tensao_kv"] == 13.8 and len(d["transformadores"]) == 6
    tr = {t["nome"]: t for t in d["transformadores"]}
    assert tr["TR-01"]["potencia_kva"] == 500 and tr["TR-01"]["medidor"]["dispositivo_id"] == ids["SIM_SCH_EM3261"]
    assert tr["TR-02"]["potencia_kva"] == 1000 and tr["TR-02"]["medidor"]["dispositivo_id"] == ids["SIM_WEG_MMW02"]
    assert tr["TR-03"]["potencia_kva"] is None and tr["TR-03"]["medidor"] is None  # a definir, nada inventado
    assert c.get("/api/diagramas/nao-existe").status_code == 404
    for pagina in ("/diagramas", "/diagramas/unifilar-geral"):
        r = c.get(pagina)
        assert r.status_code == 200 and "SGE" in r.text


def test_ao_vivo_em_lote(cliente):
    c, ids, _ = cliente
    itens = [{"dispositivo_id": ids["SIM_SCH_EM3261"], "grandezas": ["potencia_ativa_total"]},
             {"dispositivo_id": ids["SIM_WEG_MMW02"], "grandezas": ["potencia_ativa_total", "nao_existe"]}]
    r = c.post("/api/ao_vivo", json={"itens": itens}).json()
    sch, weg = r[str(ids["SIM_SCH_EM3261"])], r[str(ids["SIM_WEG_MMW02"])]
    assert sch["online"] is True and sch["valores"]["potencia_ativa_total"]["valor"] == 123.4
    assert weg["online"] is False and weg["valores"]["potencia_ativa_total"]["qualidade"] == "timeout"
    assert "nao_existe" not in weg["valores"]


def test_diagrama_com_medidor_desconhecido_e_recusado(cliente, tmp_path):
    _, _, cfg = cliente
    arq = tmp_path / "d.yaml"
    arq.write_text("slug: x\nnome: X\nbarra: {nome: B}\ntransformadores:\n  - nome: T\n    medidor: {dispositivo: NAO_EXISTE}\n", encoding="utf-8")
    cfg.diagramas = [str(arq)]
    with pytest.raises(ValueError):
        carregar_diagramas(cfg)
