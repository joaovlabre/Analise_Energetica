"""Integração: simulador Modbus TCP <-> coletor <-> SQLite <-> API, sem hardware."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.app import criar_app
from armazenamento import esquema as E
from armazenamento.gravador import sincronizar_dispositivos
from coletor.mapa import carregar_mapa
from coletor.servico import Coletor
from comum.config import Config
from tests.simulador.servidor import EscravoSimulado, ServidorSimulado

RAIZ = Path(__file__).resolve().parents[2]
MAPA_WEG = str(RAIZ / "config/mapas/weg_mmw02.csv")
MAPA_SCH = str(RAIZ / "config/mapas/schneider_gologic_em3261.csv")


def montar_config(porta: int, url: str, quadro: str = "tcp") -> Config:
    taxa = {"leitura_s": 0, "gravacao_s": 0}
    return Config.model_validate(
        dict(
            banco={"url": url},
            coleta=dict(
                ciclo_base_s=0.05,
                reconexao_s=0,
                taxas={g: taxa for g in ("instantaneo", "energia", "demanda", "qualidade", "status", "config")},
                faixas={"tensao_": {"minimo": 0, "maximo": 600}, "frequencia": {"minimo": 55, "maximo": 65}},
            ),
            barramentos=[dict(nome="sim", tipo=quadro, host="127.0.0.1", porta_tcp=porta, timeout_s=0.3, retentativas=0, pausa_entre_pedidos_ms=0)],
            dispositivos=[
                dict(nome="WEG", modelo="WEG MMW02", barramento="sim", endereco_modbus=1, mapa=MAPA_WEG),
                dict(nome="SCH", modelo="Schneider EM3261", barramento="sim", endereco_modbus=2, mapa=MAPA_SCH),
            ],
        )
    )


@pytest.fixture
async def ambiente(tmp_path, request):
    quadro = getattr(request, "param", "tcp")
    estrito = quadro == "estrito"
    quadro = "tcp" if estrito else quadro
    servidor = ServidorSimulado(
        [EscravoSimulado(1, carregar_mapa(MAPA_WEG), estrito=estrito), EscravoSimulado(2, carregar_mapa(MAPA_SCH), estrito=estrito)],
        porta=0,
        quadro=quadro,
    )
    await servidor.iniciar()
    cfg = montar_config(servidor.porta, f"sqlite:///{tmp_path / 'sge.db'}", quadro)
    engine = E.criar_engine(cfg.banco.url)
    E.criar_tabelas(engine)
    ids = sincronizar_dispositivos(engine, cfg)
    coletor = Coletor(cfg, engine, ids)
    yield servidor, coletor, engine, cfg
    for b in coletor.barramentos.values():
        b.fechar()
    await servidor.parar()


def contar(engine, tabela, *filtros):
    with engine.connect() as con:
        return con.execute(select(func.count()).select_from(tabela).where(*filtros)).scalar()


@pytest.mark.parametrize("ambiente", ["tcp", "rtu_over_tcp", "estrito"], indirect=True)
async def test_ciclo_completo_grava_valores(ambiente):
    servidor, coletor, engine, _ = ambiente
    for c in coletor.dispositivos:
        valores = await c.ciclo()
        assert valores, f"{c.cfg_disp.nome} não leu nada"
        assert c.estado.online is True
    # pontos A_VERIFICAR ficam fora; todos os utilizáveis foram lidos
    weg = coletor.dispositivos[0]
    assert contar(engine, E.leitura, E.leitura.c.dispositivo_id == weg.dispositivo_id) == len(weg.pontos)
    with engine.connect() as con:
        v = dict(con.execute(select(E.valor_atual.c.grandeza, E.valor_atual.c.valor).where(E.valor_atual.c.dispositivo_id == weg.dispositivo_id)).all())
    assert 200 < v["tensao_an"] < 240
    assert 59 < v["frequencia"] < 61
    assert v["energia_ativa_importada"] == pytest.approx(1_234_567, rel=1e-4)
    assert "energia_ativa_importada_64" not in v
    sch = coletor.dispositivos[1]
    with engine.connect() as con:
        e = con.execute(select(E.valor_atual.c.valor, E.valor_atual.c.unidade).where(
            E.valor_atual.c.dispositivo_id == sch.dispositivo_id, E.valor_atual.c.grandeza == "energia_ativa_importada")).one()
    assert e.unidade == "kWh" and e.valor == pytest.approx(1_234_567, rel=1e-4)  # INT64 Wh * 0.001


async def test_bloco_recusado_e_dividido(ambiente):
    """Com o simulador em modo estrito, blocos que cobrem buracos são recusados (exceção 02) e o coletor divide."""
    servidor, coletor, engine, _ = ambiente
    for e in servidor.escravos.values():
        e.estrito = True
    weg = coletor.dispositivos[0]
    valores = await weg.ciclo()
    assert len(valores) == len(weg.pontos)
    assert weg._divididos  # houve divisão
    assert not weg.estado.pontos_recusados


async def test_queda_e_retorno_registram_lacuna(ambiente):
    servidor, coletor, engine, _ = ambiente
    c = coletor.dispositivos[0]
    await c.ciclo()
    servidor.fora_do_ar = True
    assert await c.ciclo() is None
    assert c.estado.online is False
    with engine.connect() as con:
        quals = set(con.execute(select(E.valor_atual.c.qualidade).where(E.valor_atual.c.dispositivo_id == c.dispositivo_id)).scalars())
    assert quals == {"timeout"}
    servidor.fora_do_ar = False
    assert await c.ciclo()
    tipos = [t for (t,) in engine.connect().execute(
        select(E.evento_comunicacao.c.tipo).where(E.evento_comunicacao.c.dispositivo_id == c.dispositivo_id).order_by(E.evento_comunicacao.c.id))]
    assert tipos == ["falha", "retorno"]
    with engine.connect() as con:
        quals = set(con.execute(select(E.valor_atual.c.qualidade).where(E.valor_atual.c.dispositivo_id == c.dispositivo_id)).scalars())
    assert "timeout" not in quals


async def test_api_expoe_dados(ambiente):
    servidor, coletor, engine, cfg = ambiente
    for c in coletor.dispositivos:
        await c.ciclo()
    cliente = TestClient(criar_app(cfg, engine))
    disp = cliente.get("/api/dispositivos").json()
    assert {d["nome"] for d in disp} == {"WEG", "SCH"}
    assert all(d["online"] for d in disp)
    weg_id = next(d["id"] for d in disp if d["nome"] == "WEG")
    atual = cliente.get(f"/api/dispositivos/{weg_id}/atual").json()
    assert any(v["grandeza"] == "potencia_ativa_total" for v in atual["valores"])
    tend = cliente.get("/api/tendencia", params=dict(dispositivo_id=weg_id, grandeza="tensao_an", horas=1)).json()
    assert len(tend["pontos"]) == 1 and tend["unidade"] == "V"
    assert tend["pontos"][0][0].endswith("-03:00")  # exibido no horário de Araguaína
    assert "tensao_an" in cliente.get("/api/grandezas", params=dict(dispositivo_id=weg_id)).json()
    assert cliente.get("/api/energia", params=dict(dispositivo_id=weg_id)).status_code == 200
    assert cliente.get("/api/comunicacao").status_code == 200
    for pagina in ("/", "/tendencias", "/energia", "/comunicacao"):
        r = cliente.get(pagina)
        assert r.status_code == 200 and "SGE" in r.text
    assert cliente.get("/api/dispositivos/999/atual").status_code == 404


async def test_validar_campo_gera_planilha(ambiente, tmp_path):
    from openpyxl import load_workbook

    from ferramentas.validar_campo import gerar_excel, ler_todos

    servidor, coletor, engine, cfg = ambiente
    weg = coletor.dispositivos[0]
    pontos = carregar_mapa(MAPA_WEG)
    resultados = await ler_todos(weg.barramento.cliente, 1, pontos)
    assert len(resultados) == len(pontos) and not any(r.erro for r in resultados)
    tensao = next(r for r in resultados if r.ponto.grandeza == "tensao_an")
    assert 200 < tensao.valor_mapa < 240
    assert set(tensao.valores) == {"ABCD", "CDAB", "BADC", "DCBA"}
    arq = gerar_excel(resultados, tmp_path / "v.xlsx", {"Dispositivo": "WEG"})
    ws = load_workbook(arq).active
    assert any(c.value == "VALOR NO DISPLAY" for c in ws[3])


async def test_gateway_medidor_fora_nao_desativa_pontos(ambiente):
    """Arquitetura de campo: medidores em série -> gateway RS485/TCP. Um medidor cai, o gateway responde 0B."""
    servidor, coletor, engine, _ = ambiente
    weg, sch = coletor.dispositivos
    await weg.ciclo()
    await sch.ciclo()
    servidor.escravos[2].fora_do_ar = True  # Schneider desligado; WEG segue respondendo pelo mesmo gateway
    assert await sch.ciclo() is None
    assert sch.estado.online is False
    assert "0B" in sch.estado.ultimo_erro
    assert not sch.estado.pontos_recusados  # não confundiu com endereço inválido
    assert await weg.ciclo() and weg.estado.online is True
    servidor.escravos[2].fora_do_ar = False
    valores = await sch.ciclo()
    assert valores and len(valores) == len(sch.pontos) and sch.estado.online is True
    with engine.connect() as con:
        tipos = con.execute(select(E.evento_comunicacao.c.tipo).where(
            E.evento_comunicacao.c.dispositivo_id == sch.dispositivo_id).order_by(E.evento_comunicacao.c.id)).scalars().all()
    assert tipos == ["falha", "retorno"]


async def test_gateway_inteiro_fora(ambiente):
    """Gateway ou switch sem resposta: todos os medidores atrás dele ficam sem comunicação."""
    servidor, coletor, engine, _ = ambiente
    servidor.fora_do_ar = True
    for c in coletor.dispositivos:
        assert await c.ciclo() is None
        assert c.estado.online is False and not c.estado.pontos_recusados
