from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select, text

from armazenamento import esquema as E
from ferramentas.migrar_banco import ErroMigracao, migrar

T0 = datetime(2026, 11, 17, 18, 0)


def _banco_antigo(caminho):
    """Banco no formato anterior: leitura com dispositivo_id/grandeza/unidade em cada linha."""
    eng = create_engine(f"sqlite:///{caminho}")
    with eng.begin() as con:
        con.execute(text("CREATE TABLE dispositivo (id INTEGER PRIMARY KEY, nome VARCHAR(80) UNIQUE NOT NULL, modelo VARCHAR(80) NOT NULL, "
                         "origem VARCHAR(20) NOT NULL, barramento VARCHAR(80), endereco_modbus INTEGER, mapa VARCHAR(255), "
                         "local VARCHAR(120), ativo BOOLEAN NOT NULL)"))
        con.execute(text("CREATE TABLE leitura (id INTEGER PRIMARY KEY, ts_utc DATETIME NOT NULL, dispositivo_id INTEGER NOT NULL, "
                         "grandeza VARCHAR(60) NOT NULL, valor FLOAT, unidade VARCHAR(12) NOT NULL, qualidade VARCHAR(12) NOT NULL)"))
        con.execute(text("INSERT INTO dispositivo VALUES (2, 'SCH', 'EM3261', 'modbus_rtu', 'rs485', 2, 'm.csv', 'Bancada', 1)"))
        for m in range(3):
            ts = (T0 + timedelta(minutes=m)).isoformat(sep=" ")
            con.execute(text("INSERT INTO leitura (ts_utc, dispositivo_id, grandeza, valor, unidade, qualidade) VALUES "
                             f"('{ts}', 2, 'tensao_an', {213 + m}, 'V', 'ok'), ('{ts}', 2, 'energia_aparente', 0.531, 'kVAh', 'ok')"))
        # repetida no mesmo instante: deve ser ignorada
        con.execute(text(f"INSERT INTO leitura (ts_utc, dispositivo_id, grandeza, valor, unidade, qualidade) VALUES "
                         f"('{T0.isoformat(sep=' ')}', 2, 'tensao_an', 999, 'V', 'ok')"))
    return eng


def test_migra_formato_antigo(tmp_path):
    origem = _banco_antigo(tmp_path / "antigo.db")
    destino = E.criar_engine(f"sqlite:///{tmp_path / 'novo.db'}")
    contagem = migrar(origem, destino, saida=lambda *_: None)
    assert contagem["dispositivo"] == 1
    assert contagem["ponto"] == 2
    assert contagem["leitura"] == 6
    with destino.connect() as con:
        tensoes = con.execute(
            select(E.leitura.c.valor).select_from(E.leitura.join(E.ponto, E.ponto.c.id == E.leitura.c.ponto_id))
            .where(E.ponto.c.grandeza == "tensao_an", E.ponto.c.dispositivo_id == 2).order_by(E.leitura.c.ts_utc)
        ).scalars().all()
    assert tensoes == [213, 214, 215]
    # origem intacta
    with origem.connect() as con:
        assert con.execute(text("SELECT count(*) FROM leitura")).scalar() == 7


def test_recusa_destino_com_dados(tmp_path):
    origem = _banco_antigo(tmp_path / "antigo.db")
    destino = E.criar_engine(f"sqlite:///{tmp_path / 'novo.db'}")
    migrar(origem, destino, saida=lambda *_: None)
    with pytest.raises(ErroMigracao):
        migrar(origem, destino, saida=lambda *_: None)
