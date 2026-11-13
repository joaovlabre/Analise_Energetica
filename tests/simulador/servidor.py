"""Servidor Modbus TCP simulado (asyncio), com vários escravos (como um gateway TCP/RS-485).

Suporta somente leitura (FC 01, 02, 03, 04). Qualquer outra função responde exceção 01.
Modos de quadro: 'tcp' (MBAP, Modbus TCP) e 'rtu_over_tcp' (quadro RTU com CRC sobre TCP).
Injeção de falhas: quedas (sem resposta) e reset dos totalizadores, para testar o coletor.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass, field

from coletor.mapa import Ponto
from tests.simulador.modelo import EstadoEletrico, gerar_registros

log = logging.getLogger("simulador")


def crc16(dados: bytes) -> int:
    crc = 0xFFFF
    for b in dados:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


@dataclass
class EscravoSimulado:
    unidade: int
    pontos: list[Ponto]
    estado: EstadoEletrico = field(default_factory=EstadoEletrico)
    estrito: bool = False  # True: endereço não mapeado -> exceção 02 (como alguns medidores reais)
    fora_do_ar: bool = False  # medidor desligado / cabo RS-485 interrompido
    tabela: dict[int, dict[int, int]] = field(default_factory=dict)

    def atualizar(self) -> None:
        self.estado.avancar()
        self.tabela = gerar_registros(self.pontos, self.estado)

    def ler(self, funcao: int, inicio: int, quantidade: int) -> list[int] | int:
        """Retorna registradores ou um código de exceção Modbus (int)."""
        if funcao not in (1, 2, 3, 4):
            return 0x01
        limite = 2000 if funcao in (1, 2) else 125
        if quantidade < 1 or quantidade > limite:
            return 0x03
        regs = self.tabela.get(funcao, {})
        saida = []
        for a in range(inicio, inicio + quantidade):
            if a not in regs and self.estrito:
                return 0x02
            saida.append(regs.get(a, 0))
        return saida


@dataclass
class Falhas:
    quedas: list[tuple[float, float]] = field(default_factory=list)  # gateway inteiro sem responder (início_s, duração_s)
    quedas_escravo: list[tuple[int, float, float]] = field(default_factory=list)  # (id, início_s, duração_s): só um medidor
    resets: list[float] = field(default_factory=list)  # instantes (s) para zerar os totalizadores


class ServidorSimulado:
    def __init__(self, escravos: list[EscravoSimulado], host="127.0.0.1", porta=5020, quadro="tcp", falhas: Falhas | None = None,
                 gateway: bool = True):
        # gateway=True: comporta-se como conversor RS485/TCP (escravo ausente -> exceção 0B);
        # gateway=False: comporta-se como medidor com Ethernet nativa (escravo ausente -> silêncio)
        self.gateway = gateway
        self.escravos = {e.unidade: e for e in escravos}
        self.host, self.porta, self.quadro = host, porta, quadro
        self.falhas = falhas or Falhas()
        self._server: asyncio.base_events.Server | None = None
        self._tarefa: asyncio.Task | None = None
        self._t0 = time.monotonic()
        self._resets_feitos: set[float] = set()
        self.pedidos = 0
        self.fora_do_ar = False  # controle manual (testes)

    # ------------------------------------------------------------------ ciclo
    async def iniciar(self) -> None:
        self._t0 = time.monotonic()
        for e in self.escravos.values():
            e.atualizar()
        self._server = await asyncio.start_server(self._atender, self.host, self.porta)
        self.porta = self._server.sockets[0].getsockname()[1]
        self._tarefa = asyncio.create_task(self._loop_atualizacao())
        log.info("simulador ouvindo em %s:%s (%s), escravos %s", self.host, self.porta, self.quadro, sorted(self.escravos))

    async def parar(self) -> None:
        if self._tarefa:
            self._tarefa.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _loop_atualizacao(self) -> None:
        while True:
            t = time.monotonic() - self._t0
            for instante in self.falhas.resets:
                if t >= instante and instante not in self._resets_feitos:
                    self._resets_feitos.add(instante)
                    for e in self.escravos.values():
                        e.estado.resetar_totalizadores()
                    log.warning("simulador: totalizadores zerados (t=%.0fs)", t)
            for e in self.escravos.values():
                e.atualizar()
            await asyncio.sleep(0.5)

    def _escravo_em_queda(self, escravo: EscravoSimulado) -> bool:
        if escravo.fora_do_ar:
            return True
        t = time.monotonic() - self._t0
        return any(uid == escravo.unidade and ini <= t < ini + dur for uid, ini, dur in self.falhas.quedas_escravo)

    def _em_queda(self) -> bool:
        if self.fora_do_ar:
            return True
        t = time.monotonic() - self._t0
        return any(ini <= t < ini + dur for ini, dur in self.falhas.quedas)

    # ------------------------------------------------------------------ protocolo
    def _processar_pdu(self, unidade: int, pdu: bytes) -> bytes | None:
        escravo = self.escravos.get(unidade)
        funcao = pdu[0]
        if escravo is None or self._escravo_em_queda(escravo):
            # gateway: o medidor não respondeu no RS-485 -> exceção 0B; sem gateway: silêncio
            return bytes([funcao | 0x80, 0x0B]) if self.gateway else None
        if funcao not in (1, 2, 3, 4) or len(pdu) < 5:
            return bytes([funcao | 0x80, 0x01])
        inicio, quantidade = struct.unpack(">HH", pdu[1:5])
        r = escravo.ler(funcao, inicio, quantidade)
        if isinstance(r, int):
            return bytes([funcao | 0x80, r])
        if funcao in (1, 2):
            n = (quantidade + 7) // 8
            bits = bytearray(n)
            for i, v in enumerate(r):
                if v:
                    bits[i // 8] |= 1 << (i % 8)
            return bytes([funcao, n]) + bytes(bits)
        corpo = b"".join(struct.pack(">H", v) for v in r)
        return bytes([funcao, len(corpo)]) + corpo

    async def _atender(self, leitor: asyncio.StreamReader, escritor: asyncio.StreamWriter) -> None:
        try:
            while True:
                if self.quadro == "tcp":
                    cab = await leitor.readexactly(7)
                    tid, pid, tam, unidade = struct.unpack(">HHHB", cab)
                    pdu = await leitor.readexactly(tam - 1)
                else:  # rtu_over_tcp: pedidos de leitura têm 8 bytes
                    quadro = await leitor.readexactly(8)
                    if crc16(quadro[:-2]) != struct.unpack("<H", quadro[-2:])[0]:
                        continue  # CRC inválido: escravo real fica em silêncio
                    unidade, pdu = quadro[0], quadro[1:-2]
                self.pedidos += 1
                if self._em_queda():
                    continue
                resp = self._processar_pdu(unidade, pdu)
                if resp is None:
                    continue
                if self.quadro == "tcp":
                    escritor.write(struct.pack(">HHHB", tid, pid, len(resp) + 1, unidade) + resp)
                else:
                    corpo = bytes([unidade]) + resp
                    escritor.write(corpo + struct.pack("<H", crc16(corpo)))
                await escritor.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            escritor.close()
