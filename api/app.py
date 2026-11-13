"""API (FastAPI) e telas web. Somente leitura do banco."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from armazenamento.esquema import criar_engine, criar_tabelas
from comum.config import Config
from comum.tempo import agora_utc, para_local

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"

# grandezas mostradas em destaque no painel (se existirem no medidor)
DESTAQUES = [
    "potencia_ativa_total",
    "potencia_reativa_total",
    "potencia_aparente_total",
    "fp_total",
    "tensao_ff_media",
    "tensao_fn_media",
    "corrente_media",
    "frequencia",
    "energia_ativa_importada",
    "energia_reativa_importada",
]


def _iso(dt: datetime | None) -> str | None:
    return para_local(dt).isoformat(timespec="seconds") if dt else None


def criar_app(cfg: Config, engine: Engine | None = None) -> FastAPI:
    engine = engine or criar_engine(cfg.banco.url)
    criar_tabelas(engine)
    app = FastAPI(title="SGE Agronorte — Gestão de Energia", version="0.1.0")
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
    templates = Jinja2Templates(directory=WEB / "templates")

    # ------------------------------------------------------------------ API
    @app.get("/api/saude")
    def saude():
        return {"status": "ok", "agora": _iso(agora_utc())}

    @app.get("/api/dispositivos")
    def dispositivos():
        D, S = E.dispositivo, E.estado_comunicacao
        q = select(D, S.c.online, S.c.ts_ultima_ok_utc, S.c.pedidos_ok, S.c.pedidos_falha, S.c.ultimo_erro).select_from(
            D.outerjoin(S, S.c.dispositivo_id == D.c.id)
        ).order_by(D.c.nome)
        with engine.connect() as con:
            linhas = con.execute(q).mappings().all()
        return [
            dict(
                id=l["id"], nome=l["nome"], modelo=l["modelo"], origem=l["origem"], barramento=l["barramento"],
                endereco_modbus=l["endereco_modbus"], local=l["local"], ativo=l["ativo"], online=l["online"],
                ultima_ok=_iso(l["ts_ultima_ok_utc"]), pedidos_ok=l["pedidos_ok"], pedidos_falha=l["pedidos_falha"],
                ultimo_erro=l["ultimo_erro"],
            )
            for l in linhas
        ]

    @app.get("/api/dispositivos/{dispositivo_id}/atual")
    def valores_atuais(dispositivo_id: int):
        V = E.valor_atual
        with engine.connect() as con:
            if con.execute(select(E.dispositivo.c.id).where(E.dispositivo.c.id == dispositivo_id)).first() is None:
                raise HTTPException(404, "dispositivo não encontrado")
            linhas = con.execute(select(V).where(V.c.dispositivo_id == dispositivo_id).order_by(V.c.grupo, V.c.grandeza)).mappings().all()
        valores = [
            dict(grandeza=l["grandeza"], valor=l["valor"], unidade=l["unidade"], qualidade=l["qualidade"], grupo=l["grupo"], ts=_iso(l["ts_utc"]))
            for l in linhas
        ]
        return {"dispositivo_id": dispositivo_id, "destaques": DESTAQUES, "valores": valores}

    @app.get("/api/grandezas")
    def grandezas(dispositivo_id: int):
        L = E.leitura
        with engine.connect() as con:
            r = con.execute(select(L.c.grandeza).distinct().where(L.c.dispositivo_id == dispositivo_id).order_by(L.c.grandeza)).scalars().all()
        return list(r)

    @app.get("/api/tendencia")
    def tendencia(dispositivo_id: int, grandeza: str, horas: float = Query(24, gt=0, le=24 * 92)):
        L = E.leitura
        desde = agora_utc() - timedelta(hours=horas)
        q = (
            select(L.c.ts_utc, L.c.valor, L.c.unidade, L.c.qualidade)
            .where(and_(L.c.dispositivo_id == dispositivo_id, L.c.grandeza == grandeza, L.c.ts_utc >= desde))
            .order_by(L.c.ts_utc)
        )
        with engine.connect() as con:
            linhas = con.execute(q).all()
        unidade = linhas[-1].unidade if linhas else ""
        return {"grandeza": grandeza, "unidade": unidade, "pontos": [[_iso(l.ts_utc), l.valor, l.qualidade] for l in linhas]}

    @app.get("/api/energia")
    def energia(dispositivo_id: int, grandeza: str = "energia_ativa_importada", horas: float = Query(24, gt=0, le=24 * 92)):
        EI = E.energia_intervalo
        desde = agora_utc() - timedelta(hours=horas)
        q = (
            select(EI)
            .where(and_(EI.c.dispositivo_id == dispositivo_id, EI.c.grandeza == grandeza, EI.c.ts_inicio_utc >= desde))
            .order_by(EI.c.ts_inicio_utc)
        )
        with engine.connect() as con:
            linhas = con.execute(q).mappings().all()
        total = sum(l["consumo"] for l in linhas)
        return {
            "grandeza": grandeza,
            "unidade": linhas[-1]["unidade"] if linhas else "",
            "total": total,
            "intervalos": [
                dict(inicio=_iso(l["ts_inicio_utc"]), consumo=l["consumo"], qualidade=l["qualidade"], flag=l["flag"], motivo=l["motivo"])
                for l in linhas
            ],
        }

    @app.get("/api/comunicacao")
    def comunicacao(dispositivo_id: int | None = None, limite: int = Query(200, gt=0, le=5000)):
        EV, D = E.evento_comunicacao, E.dispositivo
        q = select(EV, D.c.nome).select_from(EV.join(D, D.c.id == EV.c.dispositivo_id)).order_by(EV.c.ts_utc.desc(), EV.c.id.desc()).limit(limite)
        if dispositivo_id is not None:
            q = q.where(EV.c.dispositivo_id == dispositivo_id)
        with engine.connect() as con:
            linhas = con.execute(q).mappings().all()
        return [
            dict(ts=_iso(l["ts_utc"]), dispositivo=l["nome"], tipo=l["tipo"], detalhe=l["detalhe"], duracao_s=l["duracao_s"])
            for l in linhas
        ]

    # ------------------------------------------------------------------ telas
    def _pagina(nome: str, request: Request, titulo: str):
        return templates.TemplateResponse(request, nome, {"titulo": titulo})

    @app.get("/", response_class=HTMLResponse)
    def painel(request: Request):
        return _pagina("painel.html", request, "Painel")

    @app.get("/tendencias", response_class=HTMLResponse)
    def tela_tendencias(request: Request):
        return _pagina("tendencias.html", request, "Tendências")

    @app.get("/energia", response_class=HTMLResponse)
    def tela_energia(request: Request):
        return _pagina("energia.html", request, "Energia 15 min")

    @app.get("/comunicacao", response_class=HTMLResponse)
    def tela_comunicacao(request: Request):
        return _pagina("comunicacao.html", request, "Comunicação")

    return app
