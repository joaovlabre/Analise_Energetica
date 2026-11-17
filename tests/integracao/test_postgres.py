"""Integração com PostgreSQL + TimescaleDB (docker compose up -d).

Cria um banco temporário sge_teste_<aleatório>, roda o esquema, grava leituras, agrega e comprime.
Pulado se o .env não existir ou o servidor não responder.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from armazenamento import esquema as E
from armazenamento.agregacao import agregar
from armazenamento.gravador import gravar_leituras, ids_pontos
from comum.config import Agregacao, expandir_variaveis, ler_env

RAIZ = Path(__file__).resolve().parents[2]
URL = "postgresql+psycopg://${SGE_DB_USUARIO}:${SGE_DB_SENHA}@127.0.0.1:${SGE_DB_PORTA}/"
# dados recentes: a política automática (comprime blocos com mais de 7 dias) não disputa com o teste
T0 = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=4)).replace(minute=0, second=0, microsecond=0)


@pytest.fixture(scope="module")
def engine():
    env = ler_env(RAIZ / ".env")
    try:
        base = expandir_variaveis(URL, env)
    except ValueError:
        pytest.skip("sem .env com as credenciais do PostgreSQL")
    admin = create_engine(base + env.get("SGE_DB_NOME", "sge"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as con:
            con.execute(text("SELECT 1"))
    except Exception as erro:  # servidor fora
        pytest.skip(f"PostgreSQL indisponível: {erro.__class__.__name__}")
    nome = f"sge_teste_{secrets.token_hex(4)}"
    with admin.connect() as con:
        con.execute(text(f'CREATE DATABASE "{nome}"'))
    eng = E.criar_engine(base + nome)
    try:
        E.criar_tabelas(eng)
        E.criar_tabelas(eng)  # idempotente
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def test_leitura_e_hypertable_comprimida(engine):
    with engine.connect() as con:
        info = con.execute(text(
            "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'leitura'"
        )).scalar()
    assert info is True


def test_grava_agrega_e_le_bloco_comprimido(engine):
    with engine.begin() as con:
        disp = con.execute(E.dispositivo.insert().values(nome="PG1", modelo="X", origem="modbus_tcp", ativo=True)).inserted_primary_key[0]
    # 2 h de totalizador a cada minuto (+1 kWh/min) e um instantâneo com NaN tratado como None
    linhas = [dict(ts_utc=T0 + timedelta(minutes=m), dispositivo_id=disp, grandeza="energia_ativa_importada",
                   valor=1000.0 + m, unidade="kWh", qualidade="ok") for m in range(121)]
    linhas.append(dict(ts_utc=T0, dispositivo_id=disp, grandeza="potencia_ativa_total", valor=None, unidade="kW", qualidade="fora_faixa"))
    gravar_leituras(engine, linhas)

    pid = ids_pontos(engine, {(disp, "energia_ativa_importada", "kWh")})[(disp, "energia_ativa_importada", "kWh")]
    with engine.connect() as con:
        assert con.execute(select(func.count()).select_from(E.leitura).where(E.leitura.c.ponto_id == pid)).scalar() == 121
        assert con.execute(select(func.count()).select_from(E.ponto).where(E.ponto.c.dispositivo_id == disp)).scalar() == 2

    cfg = Agregacao(intervalo_min=15, grandezas=["energia_ativa_importada"], max_lacuna_min=5)
    assert agregar(engine, cfg, [disp], agora=T0 + timedelta(hours=3)) == 8
    with engine.connect() as con:
        consumos = con.execute(select(E.energia_intervalo.c.consumo).where(E.energia_intervalo.c.dispositivo_id == disp)).scalars().all()
    assert consumos == pytest.approx([15.0] * 8)

    # comprime os blocos e confere que a leitura continua igual
    with engine.begin() as con:
        con.execute(text("SELECT compress_chunk(c, if_not_compressed => TRUE) FROM show_chunks('leitura') c"))
        comprimidos = con.execute(text(
            "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'leitura' AND is_compressed"
        )).scalar()
    assert comprimidos >= 1
    with engine.connect() as con:
        soma = con.execute(select(func.sum(E.leitura.c.valor)).where(E.leitura.c.ponto_id == pid)).scalar()
    assert soma == pytest.approx(sum(1000.0 + m for m in range(121)))
