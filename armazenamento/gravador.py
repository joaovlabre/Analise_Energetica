"""Gravação no banco. Histórico: apenas INSERT."""
from __future__ import annotations

import weakref
from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

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


# cache (dispositivo_id, grandeza, unidade) -> ponto.id, um por engine
_pontos: "weakref.WeakKeyDictionary[Engine, dict[tuple[int, str, str], int]]" = weakref.WeakKeyDictionary()


def _buscar_ponto(con: Connection, chave: tuple[int, str, str]) -> int | None:
    P = E.ponto
    disp, grandeza, unidade = chave
    return con.execute(
        select(P.c.id).where(P.c.dispositivo_id == disp, P.c.grandeza == grandeza, P.c.unidade == unidade)
    ).scalar()


def ids_pontos(engine: Engine, chaves: set[tuple[int, str, str]]) -> dict[tuple[int, str, str], int]:
    """Resolve (dispositivo_id, grandeza, unidade) para ponto.id, cadastrando o ponto se for novo."""
    cache = _pontos.setdefault(engine, {})
    faltam = [c for c in chaves if c not in cache]
    for chave in faltam:
        with engine.begin() as con:
            pid = _buscar_ponto(con, chave)
        if pid is None:
            try:
                with engine.begin() as con:
                    pid = con.execute(
                        insert(E.ponto).values(dispositivo_id=chave[0], grandeza=chave[1], unidade=chave[2])
                    ).inserted_primary_key[0]
            except IntegrityError:  # outro processo cadastrou ao mesmo tempo
                with engine.begin() as con:
                    pid = _buscar_ponto(con, chave)
        cache[chave] = pid
    return {c: cache[c] for c in chaves}


def gravar_leituras(engine: Engine, linhas: list[dict]) -> None:
    """linhas: dicts com ts_utc, dispositivo_id, grandeza, valor, unidade, qualidade."""
    if not linhas:
        return
    ids = ids_pontos(engine, {(l["dispositivo_id"], l["grandeza"], l["unidade"]) for l in linhas})
    registros = [
        dict(ponto_id=ids[(l["dispositivo_id"], l["grandeza"], l["unidade"])], ts_utc=l["ts_utc"],
             valor=l["valor"], qualidade=l["qualidade"])
        for l in linhas
    ]
    with engine.begin() as con:
        con.execute(insert(E.leitura), registros)


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
        pedidos_ok=pedidos_ok,
        pedidos_falha=pedidos_falha,
        ultimo_erro=(ultimo_erro or "")[:255] or None,
    )
    if ts_ultima_ok is not None:  # coletor recém-iniciado sem comunicação não apaga a última leitura boa do banco
        dados["ts_ultima_ok_utc"] = ts_ultima_ok
    with engine.begin() as con:
        r = con.execute(
            update(E.estado_comunicacao).where(E.estado_comunicacao.c.dispositivo_id == dispositivo_id).values(**dados)
        )
        if r.rowcount == 0:
            con.execute(insert(E.estado_comunicacao).values(dispositivo_id=dispositivo_id, **dados))
