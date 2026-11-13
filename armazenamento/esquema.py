"""Esquema do banco (SQLAlchemy Core). Portável: SQLite agora, MS SQL Server depois.

Regras:
- Datas em UTC, sem fuso (DateTime ingênuo).
- Histórico só recebe INSERT. Correções viram novos registros em `correcao`.
- `valor_atual` é um cache do último valor lido (para a tela), não é histórico.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

# BIGINT autoincremento no SQL Server; INTEGER PRIMARY KEY (rowid) no SQLite
IdGrande = BigInteger().with_variant(Integer, "sqlite")

dispositivo = Table(
    "dispositivo",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(80), nullable=False, unique=True),
    Column("modelo", String(80), nullable=False),
    Column("origem", String(20), nullable=False),  # modbus_rtu | modbus_tcp | manual | importacao
    Column("barramento", String(80)),
    Column("endereco_modbus", Integer),
    Column("mapa", String(255)),
    Column("local", String(120)),
    Column("ativo", Boolean, nullable=False, default=True),
)

leitura = Table(
    "leitura",
    metadata,
    Column("id", IdGrande, primary_key=True, autoincrement=True),
    Column("ts_utc", DateTime, nullable=False),
    Column("dispositivo_id", Integer, ForeignKey("dispositivo.id"), nullable=False),
    Column("grandeza", String(60), nullable=False),
    Column("valor", Float),  # NULL quando o medidor devolve NaN
    Column("unidade", String(12), nullable=False),
    Column("qualidade", String(12), nullable=False),  # ok | timeout | fora_faixa | estimado | manual
)
Index("ix_leitura_disp_grand_ts", leitura.c.dispositivo_id, leitura.c.grandeza, leitura.c.ts_utc)

valor_atual = Table(
    "valor_atual",
    metadata,
    Column("dispositivo_id", Integer, ForeignKey("dispositivo.id"), primary_key=True),
    Column("grandeza", String(60), primary_key=True),
    Column("ts_utc", DateTime, nullable=False),
    Column("valor", Float),
    Column("unidade", String(12), nullable=False),
    Column("qualidade", String(12), nullable=False),
    Column("grupo", String(12), nullable=False),
)

estado_comunicacao = Table(
    "estado_comunicacao",
    metadata,
    Column("dispositivo_id", Integer, ForeignKey("dispositivo.id"), primary_key=True),
    Column("online", Boolean, nullable=False),
    Column("ts_ultima_ok_utc", DateTime),
    Column("ts_atualizacao_utc", DateTime, nullable=False),
    Column("pedidos_ok", BigInteger, nullable=False, default=0),
    Column("pedidos_falha", BigInteger, nullable=False, default=0),
    Column("ultimo_erro", String(255)),
)

evento_comunicacao = Table(
    "evento_comunicacao",
    metadata,
    Column("id", IdGrande, primary_key=True, autoincrement=True),
    Column("ts_utc", DateTime, nullable=False),
    Column("dispositivo_id", Integer, ForeignKey("dispositivo.id"), nullable=False),
    Column("tipo", String(20), nullable=False),  # falha | retorno | excecao_modbus | inicio | fim
    Column("detalhe", String(255)),
    Column("duracao_s", Float),  # em 'retorno': tamanho da lacuna
)
Index("ix_evento_disp_ts", evento_comunicacao.c.dispositivo_id, evento_comunicacao.c.ts_utc)

energia_intervalo = Table(
    "energia_intervalo",
    metadata,
    Column("id", IdGrande, primary_key=True, autoincrement=True),
    Column("ts_inicio_utc", DateTime, nullable=False),
    Column("intervalo_min", Integer, nullable=False),
    Column("dispositivo_id", Integer, ForeignKey("dispositivo.id"), nullable=False),
    Column("grandeza", String(60), nullable=False),
    Column("consumo", Float, nullable=False),
    Column("unidade", String(12), nullable=False),
    Column("qualidade", String(12), nullable=False),  # ok | estimado
    Column("flag", String(40)),  # lacuna | reset | incompleto | ...
    Column("motivo", String(255)),
    Column("ts_calculo_utc", DateTime, nullable=False),
    UniqueConstraint("dispositivo_id", "grandeza", "intervalo_min", "ts_inicio_utc", name="uq_energia_intervalo"),
)

producao = Table(
    "producao",
    metadata,
    Column("id", IdGrande, primary_key=True, autoincrement=True),
    Column("ts_inicio_utc", DateTime, nullable=False),
    Column("ts_fim_utc", DateTime, nullable=False),
    Column("linha", String(60), nullable=False),
    Column("produto", String(80)),
    Column("quantidade_t", Float, nullable=False),
    Column("origem", String(20), nullable=False),  # manual | clp | balanca | erp | importacao
    Column("usuario", String(60)),
    Column("obs", String(255)),
    Column("ts_registro_utc", DateTime, nullable=False),
)

correcao = Table(
    "correcao",
    metadata,
    Column("id", IdGrande, primary_key=True, autoincrement=True),
    Column("ts_registro_utc", DateTime, nullable=False),
    Column("tabela", String(40), nullable=False),
    Column("registro_id", BigInteger, nullable=False),
    Column("campo", String(40), nullable=False),
    Column("valor_novo", Float),
    Column("flag", String(40), nullable=False),
    Column("motivo", String(255), nullable=False),
    Column("usuario", String(60), nullable=False),
)


def criar_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        from pathlib import Path

        caminho = url.removeprefix("sqlite:///")
        if caminho and caminho != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")  # coletor grava enquanto a API lê
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def criar_tabelas(engine: Engine) -> None:
    metadata.create_all(engine)
