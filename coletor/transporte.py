"""Cliente Modbus (pymodbus async) — SOMENTE LEITURA.

Esta classe expõe apenas as funções 01, 02, 03 e 04. Funções de escrita (05, 06, 15, 16)
não estão implementadas no coletor (escrita, se necessária, será implementada à parte).
"""
from __future__ import annotations

import logging

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from comum.config import Barramento

log = logging.getLogger("coletor.transporte")


class ErroComunicacao(Exception):
    """Sem resposta, timeout, porta indisponível, conexão recusada, gateway sem caminho até o escravo."""


# Exceções que indicam falha de comunicação (e não um endereço/função inválidos):
# o dispositivo fica "sem comunicação" e é tentado de novo, sem desativar pontos.
EXCECOES_TRANSITORIAS = {
    0x05: "escravo ocupado processando (ACK)",
    0x06: "escravo ocupado",
    0x0A: "gateway sem caminho até o escravo",
    0x0B: "medidor não respondeu ao gateway",
}


class ErroExcecaoModbus(Exception):
    """O escravo respondeu com exceção Modbus (ex.: 02 = endereço ilegal)."""

    def __init__(self, codigo: int, mensagem: str = ""):
        super().__init__(mensagem or f"exceção Modbus {codigo:02d}")
        self.codigo = codigo


def _trace(nome: str):
    def trace_packet(enviando: bool, dados: bytes) -> bytes:
        if log.isEnabledFor(logging.DEBUG):
            log.debug("[%s] %s %s", nome, "TX" if enviando else "RX", dados.hex(" "))
        return dados

    return trace_packet


class ClienteModbus:
    def __init__(self, barramento: Barramento):
        self.barramento = barramento
        self._falhas_seguidas = 0
        b = barramento
        comum = dict(
            timeout=b.timeout_s,
            retries=b.retentativas,
            reconnect_delay=1.0,
            reconnect_delay_max=30.0,
            trace_packet=_trace(b.nome),
            name=b.nome,
        )
        if b.tipo == "serial":
            self._cliente = AsyncModbusSerialClient(
                b.porta,
                framer=FramerType.RTU,
                baudrate=b.baudrate,
                parity=b.paridade,
                bytesize=b.bits_dados,
                stopbits=b.bits_parada,
                **comum,
            )
        elif b.tipo == "tcp":
            self._cliente = AsyncModbusTcpClient(b.host, port=b.porta_tcp, framer=FramerType.SOCKET, **comum)
        else:  # rtu_over_tcp (gateways que repassam o quadro RTU sem converter)
            self._cliente = AsyncModbusTcpClient(b.host, port=b.porta_tcp, framer=FramerType.RTU, **comum)

    @property
    def conectado(self) -> bool:
        return bool(self._cliente.connected)

    async def conectar(self) -> None:
        try:
            ok = await self._cliente.connect()
        except (OSError, ModbusException) as e:
            raise ErroComunicacao(f"{self.barramento.nome}: falha ao conectar: {e}") from e
        if not ok:
            raise ErroComunicacao(f"{self.barramento.nome}: não foi possível conectar")

    def fechar(self) -> None:
        self._cliente.close()

    async def ler(self, funcao: int, endereco: int, quantidade: int, unidade: int) -> list[int]:
        """Lê `quantidade` registradores (FC 03/04) ou bits (FC 01/02). Retorna lista de int."""
        if not self.conectado:
            await self.conectar()
        metodo = {
            1: self._cliente.read_coils,
            2: self._cliente.read_discrete_inputs,
            3: self._cliente.read_holding_registers,
            4: self._cliente.read_input_registers,
        }.get(funcao)
        if metodo is None:
            raise ValueError(f"função {funcao} não permitida: o coletor é somente leitura")
        try:
            rr = await metodo(endereco, count=quantidade, device_id=unidade)
        except (ModbusException, OSError, TimeoutError) as e:
            # Sem resposta: após N falhas seguidas, fecha a conexão para a próxima tentativa abrir uma nova
            # (gateways podem travar a sessão TCP). Reconectar a cada falha é ruim para escravos que não
            # liberam conexões antigas (ex.: Elipse Modbus Simulator).
            # Exceções 0A/0B do gateway NÃO passam por aqui: a sessão está boa, só o medidor não respondeu.
            self._falhas_seguidas += 1
            if self._falhas_seguidas >= self.barramento.reconectar_apos_falhas:
                self._falhas_seguidas = 0
                self.fechar()
            raise ErroComunicacao(f"{self.barramento.nome} id {unidade}: {e}") from e
        self._falhas_seguidas = 0
        if rr.isError():
            codigo = getattr(rr, "exception_code", 0) or 0
            if codigo in EXCECOES_TRANSITORIAS:
                # problema de caminho/disponibilidade (gateway ou escravo ocupado), não do endereço lido
                raise ErroComunicacao(f"{self.barramento.nome} id {unidade}: {EXCECOES_TRANSITORIAS[codigo]} (exceção {codigo:02X})")
            raise ErroExcecaoModbus(codigo, f"id {unidade} FC{funcao:02d} @{endereco}+{quantidade}: exceção {codigo:02d}")
        if funcao in (1, 2):
            return [int(b) for b in rr.bits[:quantidade]]
        return list(rr.registers)
