"""Serviço de coleta: polling por dispositivo, gravação, estado de comunicação e agregação."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.engine import Engine

from armazenamento import gravador
from armazenamento.agregacao import agregar
from coletor import qualidade as Q
from coletor.barramento import Barramento
from coletor.blocos import Bloco, dividir_bloco, montar_blocos
from coletor.decodificador import aplicar_escala, decodificar
from coletor.mapa import Ponto, carregar_mapa
from coletor.transporte import ErroComunicacao, ErroExcecaoModbus
from comum.config import Config, Dispositivo
from comum.tempo import agora_utc

log = logging.getLogger("coletor")


@dataclass
class ValorLido:
    grandeza: str
    grupo: str
    valor: float | None
    unidade: str
    qualidade: str


@dataclass
class EstadoDispositivo:
    online: bool | None = None  # None = ainda não tentou
    ts_ultima_ok: datetime | None = None
    ts_queda: datetime | None = None
    ultima_tentativa: float = 0.0
    pedidos_ok: int = 0
    pedidos_falha: int = 0
    ultimo_erro: str | None = None
    pontos_recusados: set[str] = field(default_factory=set)
    ts_primeira_recusa: float | None = None  # monotonic


class ColetorDispositivo:
    def __init__(self, cfg_disp: Dispositivo, pontos: list[Ponto], barramento: Barramento, cfg: Config, dispositivo_id: int, engine: Engine | None):
        self.cfg_disp = cfg_disp
        self.cfg = cfg
        self.barramento = barramento
        self.dispositivo_id = dispositivo_id
        self.engine = engine
        self.estado = EstadoDispositivo()
        # só pontos utilizáveis (escala/unidade conhecidas) e dos grupos configurados
        self.pontos = [p for p in pontos if p.utilizavel and p.grupo in cfg_disp.grupos]
        ignorados = [p.grandeza for p in pontos if not p.utilizavel]
        if ignorados:
            log.info("%s: pontos A_VERIFICAR fora do fluxo principal: %s", cfg_disp.nome, ", ".join(ignorados))
        self._blocos_cache: dict[frozenset[str], list[Bloco]] = {}
        self._divididos: dict[tuple[int, int, int], list[Bloco]] = {}
        self._ult_leitura: dict[str, float] = {}
        self._ult_gravacao: dict[str, float] = {}
        self._recusas_notificadas: set[str] = set()

    # ------------------------------------------------------------------ leitura
    def blocos_para(self, grupos: list[str]) -> list[Bloco]:
        chave = frozenset(grupos)
        if chave not in self._blocos_cache:
            pts = [p for p in self.pontos if p.grupo in chave]
            self._blocos_cache[chave] = montar_blocos(pts, self.cfg_disp.max_registros_por_pedido, self.cfg_disp.max_buraco)
        return self._blocos_cache[chave]

    async def _ler_bloco(self, bloco: Bloco) -> list[tuple[Ponto, list[int]]]:
        """Lê um bloco; se o medidor recusar (exceção), divide em pedidos por ponto e lembra a divisão."""
        unidade = self.cfg_disp.endereco_modbus
        chave = (bloco.funcao, bloco.inicio, bloco.quantidade)
        if chave in self._divididos:
            partes = self._divididos[chave]
        else:
            try:
                regs = await self.barramento.ler(bloco.funcao, bloco.inicio, bloco.quantidade, unidade)
                self.estado.pedidos_ok += 1
                return [(p, bloco.fatiar(regs, p)) for p in bloco.pontos]
            except ErroExcecaoModbus as e:
                if len(bloco.pontos) == 1:
                    raise
                log.warning("%s: bloco FC%02d @%d+%d recusado (%s); dividindo por ponto",
                            self.cfg_disp.nome, bloco.funcao, bloco.inicio, bloco.quantidade, e)
                partes = dividir_bloco(bloco)
                self._divididos[chave] = partes
        saida = []
        for parte in partes:
            p = parte.pontos[0]
            if p.grandeza in self.estado.pontos_recusados:
                continue
            try:
                regs = await self.barramento.ler(parte.funcao, parte.inicio, parte.quantidade, unidade)
                self.estado.pedidos_ok += 1
                saida.append((p, regs))
            except ErroExcecaoModbus as e:
                self._recusar_ponto(p, e)
        return saida

    def _recusar_ponto(self, p: Ponto, e: ErroExcecaoModbus) -> None:
        if not self.estado.pontos_recusados:
            self.estado.ts_primeira_recusa = time.monotonic()
        self.estado.pontos_recusados.add(p.grandeza)
        msg = f"{p.grandeza} (reg {p.endereco_manual}, FC{p.funcao:02d}) recusado: {e}"
        if p.grandeza in self._recusas_notificadas:
            log.debug("%s: %s (continua recusado)", self.cfg_disp.nome, msg)
            return
        self._recusas_notificadas.add(p.grandeza)
        log.warning("%s: %s — ponto suspenso (nova tentativa em %.0f s ou no retorno da comunicação)",
                    self.cfg_disp.nome, msg, self.cfg.coleta.retentar_recusados_s)
        if self.engine is not None:
            gravador.registrar_evento(self.engine, self.dispositivo_id, agora_utc(), "excecao_modbus", msg)

    async def ler_grupos(self, grupos: list[str]) -> list[ValorLido]:
        """Lê os grupos pedidos. Lança ErroComunicacao se o dispositivo não responder."""
        valores: list[ValorLido] = []
        for bloco in self.blocos_para(grupos):
            try:
                pares = await self._ler_bloco(bloco)
            except ErroExcecaoModbus as e:
                self._recusar_ponto(bloco.pontos[0], e)
                continue
            for p, regs in pares:
                if p.grandeza in self.estado.pontos_recusados:
                    continue
                bruto = decodificar(regs, p.tipo, p.word_order)
                valor = aplicar_escala(bruto, p.escala)
                valor, qual = Q.avaliar(p.grandeza, valor, self.cfg.coleta.faixas)
                if log.isEnabledFor(logging.DEBUG):
                    log.debug("%s %-32s regs=%s bruto=%r -> %r %s [%s]", self.cfg_disp.nome, p.grandeza,
                              " ".join(f"{r:04X}" for r in regs), bruto, valor, p.unidade, qual)
                valores.append(ValorLido(p.grandeza, p.grupo, valor, p.unidade, qual))
                if p.grandeza in self._recusas_notificadas:
                    self._recusas_notificadas.discard(p.grandeza)
                    log.info("%s: %s voltou a ser lido", self.cfg_disp.nome, p.grandeza)
        return valores

    # ------------------------------------------------------------------ ciclo
    def liberar_recusados(self, motivo: str) -> None:
        """Volta a tentar pontos recusados e blocos divididos (o escravo pode ter sido reconfigurado)."""
        if self.estado.pontos_recusados or self._divididos:
            log.info("%s: tentando de novo %d ponto(s) recusado(s) (%s)", self.cfg_disp.nome, len(self.estado.pontos_recusados), motivo)
        self.estado.pontos_recusados.clear()
        self.estado.ts_primeira_recusa = None
        self._divididos.clear()

    def grupos_vencidos(self, agora: float) -> list[str]:
        taxas = self.cfg.coleta.taxas
        return [g for g in self.cfg_disp.grupos if agora - self._ult_leitura.get(g, -1e18) >= taxas[g].leitura_s]

    async def ciclo(self, agora_mono: float | None = None) -> list[ValorLido] | None:
        """Executa um ciclo: lê o que venceu, grava e atualiza o estado. Retorna os valores lidos."""
        agora_mono = time.monotonic() if agora_mono is None else agora_mono
        if self.estado.online is False and agora_mono - self.estado.ultima_tentativa < self.cfg.coleta.reconexao_s:
            return None
        grupos = self.grupos_vencidos(agora_mono)
        if not grupos:
            return None
        self.estado.ultima_tentativa = agora_mono
        if self.estado.ts_primeira_recusa is not None and agora_mono - self.estado.ts_primeira_recusa >= self.cfg.coleta.retentar_recusados_s:
            self.liberar_recusados("tempo de nova tentativa")
            self._ult_leitura.clear()
            grupos = self.grupos_vencidos(agora_mono)
        if self.estado.online is False:
            self.liberar_recusados("tentativa após falha de comunicação")
        ts = agora_utc()
        try:
            valores = await self.ler_grupos(grupos)
        except ErroComunicacao as e:
            self.estado.pedidos_falha += 1
            await self._ao_falhar(ts, str(e))
            return None
        for g in grupos:
            self._ult_leitura[g] = agora_mono
        await self._ao_ler(ts, agora_mono, grupos, valores)
        return valores

    async def _ao_ler(self, ts: datetime, agora_mono: float, grupos: list[str], valores: list[ValorLido]) -> None:
        estado = self.estado
        retorno = estado.online is False
        estado.online = True
        estado.ultimo_erro = None
        if self.engine is None:
            estado.ts_ultima_ok = ts
            return
        if retorno:
            duracao = (ts - estado.ts_queda).total_seconds() if estado.ts_queda else None
            log.info("%s: comunicação restabelecida (lacuna de %.0f s)", self.cfg_disp.nome, duracao or 0)
            await asyncio.to_thread(gravador.registrar_evento, self.engine, self.dispositivo_id, ts, "retorno",
                                    "comunicação restabelecida", duracao)
        estado.ts_ultima_ok = ts
        taxas = self.cfg.coleta.taxas
        gravar_grupos = {g for g in grupos if agora_mono - self._ult_gravacao.get(g, -1e18) >= taxas[g].gravacao_s}
        for g in gravar_grupos:
            self._ult_gravacao[g] = agora_mono
        historico = [
            dict(ts_utc=ts, dispositivo_id=self.dispositivo_id, grandeza=v.grandeza, valor=v.valor, unidade=v.unidade, qualidade=v.qualidade)
            for v in valores
            if v.grupo in gravar_grupos
        ]
        atuais = [dict(grandeza=v.grandeza, ts_utc=ts, valor=v.valor, unidade=v.unidade, qualidade=v.qualidade, grupo=v.grupo) for v in valores]
        await asyncio.to_thread(gravador.gravar_leituras, self.engine, historico)
        await asyncio.to_thread(gravador.atualizar_valores_atuais, self.engine, self.dispositivo_id, atuais)
        await asyncio.to_thread(self._gravar_estado, ts)

    async def _ao_falhar(self, ts: datetime, erro: str) -> None:
        estado = self.estado
        primeira_falha = estado.online is not False
        estado.online = False
        estado.ultimo_erro = erro
        self._ult_leitura.clear()  # ao voltar, lê todos os grupos de imediato (recupera totalizadores)
        if primeira_falha:
            estado.ts_queda = estado.ts_ultima_ok or ts
            log.warning("%s: sem comunicação: %s", self.cfg_disp.nome, erro)
            if self.engine is not None:
                await asyncio.to_thread(gravador.registrar_evento, self.engine, self.dispositivo_id, ts, "falha", erro)
                await asyncio.to_thread(gravador.marcar_valores_atuais, self.engine, self.dispositivo_id, Q.TIMEOUT)
        if self.engine is not None:
            await asyncio.to_thread(self._gravar_estado, ts)

    def _gravar_estado(self, ts: datetime) -> None:
        e = self.estado
        gravador.gravar_estado_comunicacao(self.engine, self.dispositivo_id, bool(e.online), ts, e.ts_ultima_ok,
                                           e.pedidos_ok, e.pedidos_falha, e.ultimo_erro)


class Coletor:
    """Orquestra todos os dispositivos ativos + agregação periódica."""

    def __init__(self, cfg: Config, engine: Engine, ids: dict[str, int], barramentos: dict[str, Barramento] | None = None):
        self.cfg = cfg
        self.engine = engine
        self.barramentos = barramentos or {b.nome: Barramento(b) for b in cfg.barramentos}
        self.dispositivos = [
            ColetorDispositivo(d, carregar_mapa(d.mapa), self.barramentos[d.barramento], cfg, ids[d.nome], engine)
            for d in cfg.dispositivos
            if d.ativo
        ]
        self.ids_ativos = [c.dispositivo_id for c in self.dispositivos]

    async def _loop_dispositivo(self, c: ColetorDispositivo, parar: asyncio.Event) -> None:
        while not parar.is_set():
            try:
                await c.ciclo()
            except Exception:  # nunca derrubar a coleta inteira por um dispositivo
                log.exception("%s: erro inesperado no ciclo", c.cfg_disp.nome)
            try:
                await asyncio.wait_for(parar.wait(), timeout=self.cfg.coleta.ciclo_base_s)
            except TimeoutError:
                pass

    async def _loop_agregacao(self, parar: asyncio.Event) -> None:
        while not parar.is_set():
            try:
                await asyncio.to_thread(agregar, self.engine, self.cfg.agregacao, self.ids_ativos)
            except Exception:
                log.exception("erro na agregação")
            try:
                await asyncio.wait_for(parar.wait(), timeout=self.cfg.agregacao.periodo_execucao_s)
            except TimeoutError:
                pass

    async def executar(self, parar: asyncio.Event) -> None:
        for c in self.dispositivos:
            await asyncio.to_thread(gravador.registrar_evento, self.engine, c.dispositivo_id, agora_utc(), "inicio", "coletor iniciado")
        tarefas = [asyncio.create_task(self._loop_dispositivo(c, parar)) for c in self.dispositivos]
        tarefas.append(asyncio.create_task(self._loop_agregacao(parar)))
        try:
            await asyncio.gather(*tarefas)
        finally:
            for c in self.dispositivos:
                await asyncio.to_thread(gravador.registrar_evento, self.engine, c.dispositivo_id, agora_utc(), "fim", "coletor parado")
            for b in self.barramentos.values():
                b.fechar()
