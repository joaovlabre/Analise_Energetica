"""Gravação no banco. Histórico: apenas INSERT."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from comum.config import Config


def sincronizar_dispositivos(engine: Engine, cfg: Config) -> dict[str, int]:
    """Cadastra/atualiza os dispositivos da configuração. Retorna {nome: id}."""
    ids: dict[str, int] = {}
    with engine.begin() as con:
        for d in cfg.dispositivos:
            bar = cfg.barramento(d.barramento)
            dados = dict(
                modelo=d.modelo,
                origem=bar.origem,
                barramento=d.barramento,
                endereco_modbus=d.endereco_modbus,
                mapa=d.mapa,
                local=d.local,
                ativo=d.ativo,
            )
            existente = con.execute(select(E.dispositivo.c.id).where(E.dispositivo.c.nome == d.nome)).scalar()
            if existente is None:
                existente = con.execute(insert(E.dispositivo).values(nome=d.nome, **dados)).inserted_primary_key[0]
            else:
                con.execute(update(E.dispositivo).where(E.dispositivo.c.id == existente).values(**dados))
            ids[d.nome] = existente
    return ids


def gravar_leituras(engine: Engine, linhas: list[dict]) -> None:
    """linhas: dicts com ts_utc, dispositivo_id, grandeza, valor, unidade, qualidade."""
    if linhas:
        with engine.begin() as con:
            con.execute(insert(E.leitura), linhas)


def atualizar_valores_atuais(engine: Engine, dispositivo_id: int, linhas: list[dict]) -> None:
    """Cache do último valor (delete + insert na mesma transação: portável SQLite/SQL Server)."""
    if not linhas:
        return
    grandezas = [l["grandeza"] for l in linhas]
    with engine.begin() as con:
        con.execute(
            delete(E.valor_atual).where(
                E.valor_atual.c.dispositivo_id == dispositivo_id, E.valor_atual.c.grandeza.in_(grandezas)
            )
        )
        con.execute(insert(E.valor_atual), [{**l, "dispositivo_id": dispositivo_id} for l in linhas])


def marcar_valores_atuais(engine: Engine, dispositivo_id: int, qualidade: str) -> None:
    with engine.begin() as con:
        con.execute(update(E.valor_atual).where(E.valor_atual.c.dispositivo_id == dispositivo_id).values(qualidade=qualidade))


def registrar_evento(engine: Engine, dispositivo_id: int, ts_utc: datetime, tipo: str, detalhe: str = "", duracao_s: float | None = None) -> None:
    with engine.begin() as con:
        con.execute(
            insert(E.evento_comunicacao).values(
                ts_utc=ts_utc, dispositivo_id=dispositivo_id, tipo=tipo, detalhe=detalhe[:255], duracao_s=duracao_s
            )
        )


def gravar_estado_comunicacao(
    engine: Engine,
    dispositivo_id: int,
    online: bool,
    ts_utc: datetime,
    ts_ultima_ok: datetime | None,
    pedidos_ok: int,
    pedidos_falha: int,
    ultimo_erro: str | None,
) -> None:
    dados = dict(
        online=online,
        ts_atualizacao_utc=ts_utc,
        ts_ultima_ok_utc=ts_ultima_ok,
        pedidos_ok=pedidos_ok,
        pedidos_falha=pedidos_falha,
        ultimo_erro=(ultimo_erro or "")[:255] or None,
    )
    with engine.begin() as con:
        r = con.execute(
            update(E.estado_comunicacao).where(E.estado_comunicacao.c.dispositivo_id == dispositivo_id).values(**dados)
        )
        if r.rowcount == 0:
            con.execute(insert(E.estado_comunicacao).values(dispositivo_id=dispositivo_id, **dados))
