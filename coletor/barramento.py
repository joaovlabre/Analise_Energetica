"""Um mestre por barramento: serializa os pedidos (RS-485 é half-duplex; gateways também)."""
from __future__ import annotations

import asyncio

from coletor.transporte import ClienteModbus
from comum.config import Barramento as CfgBarramento


class Barramento:
    def __init__(self, cfg: CfgBarramento, cliente: ClienteModbus | None = None):
        self.cfg = cfg
        self.cliente = cliente or ClienteModbus(cfg)
        self._trava = asyncio.Lock()
        self._pausa = cfg.pausa_entre_pedidos_ms / 1000.0

    async def ler(self, funcao: int, endereco: int, quantidade: int, unidade: int) -> list[int]:
        async with self._trava:
            try:
                return await self.cliente.ler(funcao, endereco, quantidade, unidade)
            finally:
                if self._pausa:
                    await asyncio.sleep(self._pausa)

    def fechar(self) -> None:
        self.cliente.fechar()
