"""Ponte de teste para o Elipse Modbus Simulator: UMA conexão com o Elipse, compartilhada.

O Elipse Modbus Simulator lida mal com vários clientes TCP (não libera conexões antigas e
deixa de responder). Esta ponte:
  1. mantém uma única conexão com o Elipse (127.0.0.1:502);
  2. escuta em 127.0.0.1:5502 e repassa as LEITURAS (FC 01-04) do coletor por essa conexão;
  3. a cada intervalo, ESCREVE (FC 16) no Elipse o totalizador de energia incrementado,
     simulando o consumo de uma carga constante.

Só escreve no simulador. Uso:
  python -m tests.simulador.ponte_elipse                       # 6,6 kW, regs 25-26 em 0,1 kWh, a cada 60 s
  python -m tests.simulador.ponte_elipse --potencia-kw 6.6 --intervalo 10 --acelerar 60
O coletor deve apontar para 127.0.0.1:5502 (config/dispositivos.elipse.yaml).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import struct
import time

log = logging.getLogger("ponte_elipse")


class ErroPonte(Exception):
    pass


class ConexaoElipse:
    """Conexão única com o Elipse; pedidos serializados por uma trava."""

    def __init__(self, host: str, porta: int, timeout: float = 2.0, reconectar_apos: int = 3):
        self.host, self.porta, self.timeout, self.reconectar_apos = host, porta, timeout, reconectar_apos
        self._leitor: asyncio.StreamReader | None = None
        self._escritor: asyncio.StreamWriter | None = None
        self._trava = asyncio.Lock()
        self._tid = 0
        self._falhas = 0

    async def _conectar(self) -> None:
        self._leitor, self._escritor = await asyncio.wait_for(asyncio.open_connection(self.host, self.porta), self.timeout)
        log.info("conectado ao Elipse em %s:%s", self.host, self.porta)

    def _fechar(self) -> None:
        if self._escritor:
            self._escritor.close()
        self._leitor = self._escritor = None

    async def pedido(self, unidade: int, pdu: bytes) -> bytes:
        """Envia um PDU e devolve o PDU de resposta."""
        async with self._trava:
            try:
                if self._escritor is None:
                    await self._conectar()
                self._tid = (self._tid + 1) & 0xFFFF
                self._escritor.write(struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, unidade) + pdu)
                await self._escritor.drain()
                while True:
                    cab = await asyncio.wait_for(self._leitor.readexactly(7), self.timeout)
                    tid, _, tam, _ = struct.unpack(">HHHB", cab)
                    resp = await asyncio.wait_for(self._leitor.readexactly(tam - 1), self.timeout)
                    if tid == self._tid:  # descarta respostas atrasadas de pedidos anteriores
                        break
                self._falhas = 0
                return resp
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                self._falhas += 1
                if self._falhas >= self.reconectar_apos or isinstance(e, (OSError, asyncio.IncompleteReadError)):
                    self._falhas = 0
                    self._fechar()
                raise ErroPonte(f"Elipse sem resposta: {e!r}") from e

    async def ler_holding(self, unidade: int, endereco: int, quantidade: int) -> list[int]:
        resp = await self.pedido(unidade, struct.pack(">BHH", 3, endereco, quantidade))
        if resp[0] & 0x80:
            raise ErroPonte(f"exceção {resp[1]:02X} ao ler @{endereco}")
        return list(struct.unpack(f">{quantidade}H", resp[2 : 2 + 2 * quantidade]))

    async def escrever_holding(self, unidade: int, endereco: int, valores: list[int]) -> None:
        n = len(valores)
        pdu = struct.pack(f">BHHB{n}H", 16, endereco, n, 2 * n, *valores)
        resp = await self.pedido(unidade, pdu)
        if resp[0] & 0x80:
            raise ErroPonte(f"exceção {resp[1]:02X} ao escrever @{endereco}")


async def servir_coletor(elipse: ConexaoElipse, host: str, porta: int) -> asyncio.base_events.Server:
    """Servidor Modbus TCP que repassa LEITURAS ao Elipse. Escritas do cliente são recusadas (exceção 01)."""

    async def atender(leitor: asyncio.StreamReader, escritor: asyncio.StreamWriter) -> None:
        try:
            while True:
                cab = await leitor.readexactly(7)
                tid, pid, tam, unidade = struct.unpack(">HHHB", cab)
                pdu = await leitor.readexactly(tam - 1)
                if pdu[0] not in (1, 2, 3, 4):
                    resp = bytes([pdu[0] | 0x80, 0x01])
                else:
                    try:
                        resp = await elipse.pedido(unidade, pdu)
                    except ErroPonte as e:
                        log.warning("leitura do coletor sem resposta do Elipse: %s", e)
                        continue  # o coletor verá timeout, como num escravo mudo
                escritor.write(struct.pack(">HHHB", tid, pid, len(resp) + 1, unidade) + resp)
                await escritor.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            escritor.close()

    servidor = await asyncio.start_server(atender, host, porta)
    log.info("ponte ouvindo em %s:%s (aponte o coletor para cá)", host, porta)
    return servidor


async def incrementar_energia(elipse: ConexaoElipse, args) -> None:
    endereco = args.registro_energia - 1  # Elipse numera a partir de 1
    unidade_kwh = args.unidade_kwh
    bruto: float | None = None
    t_ant = time.monotonic()
    while True:
        try:
            if bruto is None:
                alta, baixa = await elipse.ler_holding(args.id, endereco, 2)
                bruto = float((alta << 16) | baixa)
                t_ant = time.monotonic()
                log.info("energia inicial lida do Elipse: regs %d-%d = %d / %d -> %.1f kWh",
                         args.registro_energia, args.registro_energia + 1, alta, baixa, bruto * unidade_kwh)
            else:
                agora = time.monotonic()
                kwh = args.potencia_kw * (agora - t_ant) / 3600.0 * args.acelerar
                t_ant = agora
                bruto = (bruto + kwh / unidade_kwh) % 2**32
                inteiro = int(round(bruto))
                await elipse.escrever_holding(args.id, endereco, [(inteiro >> 16) & 0xFFFF, inteiro & 0xFFFF])
                log.info("energia: +%.3f kWh -> %.1f kWh (regs %d-%d = %d / %d)", kwh, inteiro * unidade_kwh,
                         args.registro_energia, args.registro_energia + 1, (inteiro >> 16) & 0xFFFF, inteiro & 0xFFFF)
        except ErroPonte as e:
            log.warning("não foi possível atualizar a energia: %s", e)
        await asyncio.sleep(args.intervalo)


async def principal(args) -> None:
    elipse = ConexaoElipse(args.elipse_host, args.elipse_porta)
    servidor = await servir_coletor(elipse, args.host, args.porta)
    try:
        await incrementar_energia(elipse, args)
    finally:
        servidor.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Ponte de teste para o Elipse Modbus Simulator (escreve só no simulador)")
    ap.add_argument("--elipse-host", default="127.0.0.1")
    ap.add_argument("--elipse-porta", type=int, default=502)
    ap.add_argument("--host", default="127.0.0.1", help="onde a ponte escuta o coletor")
    ap.add_argument("--porta", type=int, default=5502)
    ap.add_argument("--id", type=int, default=1)
    ap.add_argument("--registro-energia", type=int, default=25, help="registrador (base 1) da parte alta do UINT32")
    ap.add_argument("--unidade-kwh", type=float, default=0.1, help="kWh por unidade do registrador")
    ap.add_argument("--potencia-kw", type=float, default=6.6)
    ap.add_argument("--intervalo", type=float, default=60.0, help="segundos entre escritas")
    ap.add_argument("--acelerar", type=float, default=1.0, help="multiplica o consumo (testes rápidos)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(principal(args))
    except KeyboardInterrupt:
        print("ponte encerrada")


if __name__ == "__main__":
    main()
