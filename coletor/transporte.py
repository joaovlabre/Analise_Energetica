"""Cliente Modbus (pymodbus async) — SOMENTE LEITURA.

Esta classe expõe apenas as funções 01, 02, 03 e 04. Funções de escrita (05, 06, 15, 16)
não existem aqui de propósito (regra inviolável do CLAUDE.md).
"""
from __future__ import annotations

import logging

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from comum.config import Barramento

log = logging.getLogger("coletor.transporte")


class ErroComunicacao(Exception):
    """Sem resposta, timeout, porta indisponível, conexão recusada."""


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
        except ModbusException as e:
            raise ErroComunicacao(f"{self.barramento.nome} id {unidade}: {e}") from e
        except (OSError, TimeoutError) as e:
            raise ErroComunicacao(f"{self.barramento.nome} id {unidade}: {e}") from e
        if rr.isError():
            codigo = getattr(rr, "exception_code", 0) or 0
            raise ErroExcecaoModbus(codigo, f"id {unidade} FC{funcao:02d} @{endereco}+{quantidade}: exceção {codigo:02d}")
        if funcao in (1, 2):
            return [int(b) for b in rr.bits[:quantidade]]
        return list(rr.registers)
