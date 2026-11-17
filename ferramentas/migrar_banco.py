"""Copia um banco do SGE para outro, convertendo `leitura` para o formato enxuto (ponto_id).

Uso:
  python -m ferramentas.migrar_banco --origem sqlite:///dados/sge.db --destino "postgresql+psycopg://..."
  python -m ferramentas.migrar_banco --origem sqlite:///dados/x.db --destino sqlite:///dados/x_novo.db
`--destino` aceita ${VAR} do .env. A origem só é lida (nada é apagado); o destino precisa estar vazio.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import MetaData, func, insert, select, text
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from armazenamento.gravador import ids_pontos
from comum.config import expandir_variaveis, ler_env

RAIZ = Path(__file__).resolve().parent.parent
LOTE = 20_000


class ErroMigracao(Exception):
    pass


def _contar(engine: Engine, tabela) -> int:
    with engine.connect() as con:
        return con.execute(select(func.count()).select_from(tabela)).scalar()


def _copiar_tabela(origem: Engine, destino: Engine, tab_origem, tab_destino) -> int:
    colunas = [c.name for c in tab_destino.columns if c.name in tab_origem.c]
    total = 0
    with origem.connect() as co:
        resultado = co.execution_options(stream_results=True).execute(select(*[tab_origem.c[n] for n in colunas]))
        while lote := resultado.fetchmany(LOTE):
            with destino.begin() as cd:
                cd.execute(insert(tab_destino), [dict(zip(colunas, r)) for r in lote])
            total += len(lote)
    return total


def _copiar_leitura_antiga(origem: Engine, destino: Engine, L_origem) -> tuple[int, int]:
    """Formato antigo (dispositivo_id, grandeza, unidade em cada linha) -> ponto + leitura."""
    q = select(L_origem.c.dispositivo_id, L_origem.c.grandeza, L_origem.c.unidade, L_origem.c.ts_utc,
               L_origem.c.valor, L_origem.c.qualidade).order_by(
        L_origem.c.dispositivo_id, L_origem.c.grandeza, L_origem.c.unidade, L_origem.c.ts_utc)
    total = duplicadas = 0
    ultima = None
    with origem.connect() as co:
        resultado = co.execution_options(stream_results=True).execute(q)
        while lote := resultado.fetchmany(LOTE):
            ids = ids_pontos(destino, {(r.dispositivo_id, r.grandeza, r.unidade) for r in lote})
            registros = []
            for r in lote:
                chave = (ids[(r.dispositivo_id, r.grandeza, r.unidade)], r.ts_utc)
                if chave == ultima:  # mesma grandeza no mesmo instante: mantém a primeira
                    duplicadas += 1
                    continue
                ultima = chave
                registros.append(dict(ponto_id=chave[0], ts_utc=r.ts_utc, valor=r.valor, qualidade=r.qualidade))
            with destino.begin() as cd:
                cd.execute(insert(E.leitura), registros)
            total += len(registros)
    return total, duplicadas


def _ajustar_sequencias(destino: Engine) -> None:
    if destino.dialect.name != "postgresql":
        return
    with destino.begin() as con:
        for tab in E.metadata.sorted_tables:
            if "id" in tab.c and tab.c.id.autoincrement:
                con.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{tab.name}', 'id'), "
                    f"COALESCE((SELECT max(id) FROM {tab.name}), 0) + 1, false)"
                ))


def migrar(origem: Engine, destino: Engine, saida=print) -> dict[str, int]:
    meta = MetaData()
    meta.reflect(origem)
    if "leitura" not in meta.tables:
        raise ErroMigracao("a origem não tem a tabela leitura: não parece um banco do SGE")
    E.criar_tabelas(destino)
    if _contar(destino, E.leitura) or _contar(destino, E.dispositivo):
        raise ErroMigracao("o destino já tem dados; a migração só grava num banco vazio")

    contagem: dict[str, int] = {}
    for tab in E.metadata.sorted_tables:  # ordem que respeita as chaves estrangeiras
        if tab.name == "leitura" or tab.name not in meta.tables:
            continue
        contagem[tab.name] = _copiar_tabela(origem, destino, meta.tables[tab.name], tab)
        saida(f"  {tab.name}: {contagem[tab.name]}")

    L_origem = meta.tables["leitura"]
    if "ponto_id" in L_origem.c:
        contagem["leitura"] = _copiar_tabela(origem, destino, L_origem, E.leitura)
    else:
        contagem["leitura"], dup = _copiar_leitura_antiga(origem, destino, L_origem)
        contagem["ponto"] = _contar(destino, E.ponto)
        if dup:
            saida(f"  leitura: {dup} linha(s) repetida(s) no mesmo instante ignorada(s)")
    saida(f"  ponto: {contagem.get('ponto', _contar(destino, E.ponto))}")
    saida(f"  leitura: {contagem['leitura']}")
    _ajustar_sequencias(destino)
    return contagem


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origem", required=True)
    ap.add_argument("--destino", required=True)
    args = ap.parse_args(argv)
    env = ler_env(RAIZ / ".env")
    url_origem, url_destino = expandir_variaveis(args.origem, env), expandir_variaveis(args.destino, env)
    if url_origem == url_destino:
        print("origem e destino são o mesmo banco", file=sys.stderr)
        return 2
    origem, destino = E.criar_engine(url_origem), E.criar_engine(url_destino)
    print(f"migrando {origem.url.render_as_string(hide_password=True)} -> {destino.url.render_as_string(hide_password=True)}")
    try:
        migrar(origem, destino)
    except ErroMigracao as erro:
        print(f"recusado: {erro}", file=sys.stderr)
        return 1
    print("concluído")
    return 0


if __name__ == "__main__":
    sys.exit(main())
