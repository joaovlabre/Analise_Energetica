"""Ponte do Elipse: repassa leituras do coletor por UMA conexão e escreve a energia incrementada."""
import asyncio
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from coletor.decodificador import codificar
from comum.config import Barramento
from coletor.transporte import ClienteModbus
from tests.simulador.ponte_elipse import ConexaoElipse, incrementar_energia, servir_coletor


class ElipseFalso:
    """Escravo holding registers (FC 03 / FC 16) que conta conexões, como o Elipse."""

    def __init__(self, n=32):
        self.regs = [0] * n
        self.conexoes = 0

    async def atender(self, leitor, escritor):
        self.conexoes += 1
        try:
            while True:
                tid, pid, tam, uid = struct.unpack(">HHHB", await leitor.readexactly(7))
                pdu = await leitor.readexactly(tam - 1)
                fc = pdu[0]
                if fc == 3:
                    ini, n = struct.unpack(">HH", pdu[1:5])
                    resp = bytes([3, 2 * n]) + struct.pack(f">{n}H", *self.regs[ini : ini + n])
                elif fc == 16:
                    ini, n, _ = struct.unpack(">HHB", pdu[1:6])
                    self.regs[ini : ini + n] = struct.unpack(f">{n}H", pdu[6 : 6 + 2 * n])
                    resp = pdu[:5]
                else:
                    resp = bytes([fc | 0x80, 1])
                escritor.write(struct.pack(">HHHB", tid, pid, len(resp) + 1, uid) + resp)
                await escritor.drain()
        except asyncio.IncompleteReadError:
            pass


@pytest.fixture
async def elipse():
    falso = ElipseFalso()
    falso.regs[0:2] = codificar(220.0, "FLOAT32")
    falso.regs[24:26] = [0, 10000]  # 1000,0 kWh em 0,1 kWh
    srv = await asyncio.start_server(falso.atender, "127.0.0.1", 0)
    falso.porta = srv.sockets[0].getsockname()[1]
    yield falso
    srv.close()


async def test_ponte_repassa_leituras_e_incrementa_energia(elipse):
    conexao = ConexaoElipse("127.0.0.1", elipse.porta)
    ponte = await servir_coletor(conexao, "127.0.0.1", 0)
    porta_ponte = ponte.sockets[0].getsockname()[1]
    args = SimpleNamespace(id=1, registro_energia=25, unidade_kwh=0.1, potencia_kw=6.6, intervalo=0.05, acelerar=3600 * 20)
    tarefa = asyncio.create_task(incrementar_energia(conexao, args))
    cliente = ClienteModbus(Barramento(nome="t", tipo="tcp", host="127.0.0.1", porta_tcp=porta_ponte, timeout_s=1, retentativas=0))
    try:
        regs = await cliente.ler(3, 0, 2, 1)
        assert struct.unpack(">f", struct.pack(">HH", *regs))[0] == pytest.approx(220.0)
        await asyncio.sleep(0.3)
        alta, baixa = await cliente.ler(3, 24, 2, 1)
        assert ((alta << 16) | baixa) > 10000  # energia subiu
        assert elipse.conexoes == 1  # coletor + escrita pela MESMA conexão com o Elipse
    finally:
        tarefa.cancel()
        cliente.fechar()
        ponte.close()


async def test_ponte_recusa_escrita_do_cliente(elipse):
    conexao = ConexaoElipse("127.0.0.1", elipse.porta)
    ponte = await servir_coletor(conexao, "127.0.0.1", 0)
    porta = ponte.sockets[0].getsockname()[1]
    leitor, escritor = await asyncio.open_connection("127.0.0.1", porta)
    escritor.write(struct.pack(">HHHB", 1, 0, 6, 1) + struct.pack(">BHH", 6, 0, 123))  # FC 06 vindo do cliente
    await escritor.drain()
    resp = await asyncio.wait_for(leitor.read(9), 2)
    assert resp[7] == 0x86 and resp[8] == 0x01
    assert elipse.regs[0] != 123
    escritor.close()
    ponte.close()
