"""API (FastAPI) e telas web. Somente leitura do banco."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from armazenamento import esquema as E
from armazenamento.esquema import criar_engine, criar_tabelas
from api import consumo_linha
from comum.config import Config, carregar_hierarquia
from comum.diagramas import carregar_diagramas
from comum.periodo import TIPOS as TIPOS_PERIODO, resolver_periodo
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


# Painéis montados em código (fase atual: sem edição pelo usuário)
PAINEIS = [
    dict(slug="visao-geral", nome="Visão geral", descricao="Valores em tempo real de cada medidor", template="painel.html"),
    dict(slug="consumo-linha", nome="Consumo por linha",
         descricao="Energia, ração produzida e consumo específico (kWh/t) por linha de produção", template="consumo_linha.html"),
]


def _iso(dt: datetime | None) -> str | None:
    return para_local(dt).isoformat(timespec="seconds") if dt else None


def criar_app(cfg: Config, engine: Engine | None = None) -> FastAPI:
    engine = engine or criar_engine(cfg.banco.url)
    criar_tabelas(engine)
    app = FastAPI(title="SGE Agronorte — Gestão de Energia", version="0.2.0")
    app.state.engine = engine
    hierarquia = carregar_hierarquia(cfg)
    diagramas = {d.slug: d for d in carregar_diagramas(cfg)}
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

    @app.get("/api/linhas")
    def linhas():
        return [dict(nome=l.nome, descricao=l.descricao, medidores=[m.dispositivo for m in l.eletricidade]) for l in hierarquia.linhas]

    @app.get("/api/consumo_especifico")
    def consumo_especifico(linha: str, periodo: str = "mes_anterior", inicio: date | None = None, fim: date | None = None):
        try:
            lin = hierarquia.linha(linha)
        except KeyError as e:
            raise HTTPException(404, str(e.args[0]))
        if periodo not in TIPOS_PERIODO:
            raise HTTPException(422, f"período desconhecido: {periodo}")
        agora = agora_utc()
        try:
            ini, f = resolver_periodo(periodo, agora, inicio, fim)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return consumo_linha.consultar(engine, cfg, lin, ini, f, agora)

    @app.get("/api/diagramas")
    def lista_diagramas():
        return [dict(slug=d.slug, nome=d.nome, descricao=d.descricao) for d in diagramas.values()]

    @app.get("/api/diagramas/{slug}")
    def diagrama(slug: str):
        d = diagramas.get(slug)
        if d is None:
            raise HTTPException(404, "diagrama não encontrado")
        with engine.connect() as con:
            ids = dict(con.execute(select(E.dispositivo.c.nome, E.dispositivo.c.id)).all())
        dados = d.model_dump()
        for t in dados["transformadores"]:
            if t["medidor"]:
                t["medidor"]["dispositivo_id"] = ids.get(t["medidor"]["dispositivo"])
        return dados

    @app.post("/api/ao_vivo")
    def ao_vivo(itens: list[dict] = Body(..., embed=True)):
        """Valores atuais de vários dispositivos numa chamada: itens = [{dispositivo_id, grandezas: [...]}]."""
        V, S = E.valor_atual, E.estado_comunicacao
        saida = {}
        with engine.connect() as con:
            for it in itens[:200]:
                disp_id = it.get("dispositivo_id")
                grandezas = [str(g) for g in it.get("grandezas", [])][:50]
                if not isinstance(disp_id, int):
                    continue
                est = con.execute(select(S.c.online, S.c.ts_ultima_ok_utc).where(S.c.dispositivo_id == disp_id)).first()
                linhas = con.execute(select(V).where(V.c.dispositivo_id == disp_id, V.c.grandeza.in_(grandezas))).mappings().all() if grandezas else []
                saida[str(disp_id)] = dict(
                    online=est.online if est else None,
                    ultima_ok=_iso(est.ts_ultima_ok_utc) if est else None,
                    valores={l["grandeza"]: dict(valor=l["valor"], unidade=l["unidade"], qualidade=l["qualidade"], ts=_iso(l["ts_utc"])) for l in linhas},
                )
        return saida

    @app.get("/api/alarmes/resumo")
    def alarmes_resumo():
        return {"alta": 0, "media": 0, "baixa": 0}  # módulo de alarmes ainda não existe

    @app.get("/api/usuario")
    def usuario():
        return {"nome": "local", "perfil": "admin"}  # sem login por enquanto

    # ------------------------------------------------------------------ telas
    def _pagina(nome: str, request: Request, titulo: str, menu: str, **extra):
        return templates.TemplateResponse(request, nome, {"titulo": titulo, "menu": menu, "paineis": PAINEIS, **extra})

    @app.get("/")
    def raiz():
        return RedirectResponse("/paineis")

    @app.get("/paineis", response_class=HTMLResponse)
    def tela_paineis(request: Request):
        return _pagina("paineis.html", request, "Painéis", "paineis")

    @app.get("/paineis/{slug}", response_class=HTMLResponse)
    def tela_painel(request: Request, slug: str):
        p = next((p for p in PAINEIS if p["slug"] == slug), None)
        if p is None:
            raise HTTPException(404, "painel não encontrado")
        return _pagina(p["template"], request, p["nome"], "paineis", painel=p)

    @app.get("/tendencias", response_class=HTMLResponse)
    def tela_tendencias(request: Request):
        return _pagina("tendencias.html", request, "Tendências", "tendencias")

    @app.get("/energia", response_class=HTMLResponse)
    def tela_energia(request: Request):
        return _pagina("energia.html", request, "Energia 15 min", "relatorios")

    @app.get("/comunicacao", response_class=HTMLResponse)
    def tela_comunicacao(request: Request):
        return _pagina("comunicacao.html", request, "Comunicação", "comunicacao")

    @app.get("/diagramas", response_class=HTMLResponse)
    def tela_diagramas(request: Request):
        return _pagina("diagramas.html", request, "Diagramas", "diagramas", diagramas=list(diagramas.values()))

    @app.get("/diagramas/{slug}", response_class=HTMLResponse)
    def tela_diagrama(request: Request, slug: str):
        d = diagramas.get(slug)
        if d is None:
            raise HTTPException(404, "diagrama não encontrado")
        return _pagina("diagrama.html", request, d.nome, "diagramas", diagrama=d)

    @app.get("/alarmes", response_class=HTMLResponse)
    def tela_alarmes(request: Request):
        return _pagina("em_breve.html", request, "Alarmes", "alarmes", texto="O módulo de alarmes ainda não foi implementado.")

    return app
