"""Agrupamento de pontos em pedidos Modbus (registradores contíguos num único pedido)."""
from __future__ import annotations

from dataclasses import dataclass, field

from coletor.mapa import Ponto

LIMITE_REGISTROS = 125  # FC 03/04
LIMITE_BITS = 2000  # FC 01/02


@dataclass
class Bloco:
    funcao: int
    inicio: int
    quantidade: int
    pontos: list[Ponto] = field(default_factory=list)

    @property
    def fim(self) -> int:
        return self.inicio + self.quantidade

    def fatiar(self, registros: list[int], ponto: Ponto) -> list[int]:
        """Registradores de um ponto dentro da resposta do bloco."""
        i = ponto.endereco - self.inicio
        return registros[i : i + ponto.n_registros]


def montar_blocos(pontos: list[Ponto], max_registros: int = 60, max_buraco: int = 6) -> list[Bloco]:
    """Agrupa pontos da mesma função em blocos contíguos.

    - `max_registros`: tamanho máximo de um pedido (≤ 125).
    - `max_buraco`: quantos registradores não mapeados podem ficar dentro de um bloco.
      Alguns medidores respondem exceção 02 ao ler endereço não mapeado; nesse caso o coletor
      divide o bloco (ver `dividir_bloco`).
    """
    blocos: list[Bloco] = []
    por_funcao: dict[int, list[Ponto]] = {}
    for p in pontos:
        por_funcao.setdefault(p.funcao, []).append(p)
    for funcao in sorted(por_funcao):
        limite = min(max_registros, LIMITE_BITS if funcao in (1, 2) else LIMITE_REGISTROS)
        atual: Bloco | None = None
        for p in sorted(por_funcao[funcao], key=lambda p: p.endereco):
            if (
                atual is not None
                and p.endereco - atual.fim <= max_buraco
                and p.fim - atual.inicio <= limite
            ):
                atual.quantidade = max(atual.fim, p.fim) - atual.inicio
                atual.pontos.append(p)
            else:
                atual = Bloco(funcao=funcao, inicio=p.endereco, quantidade=p.n_registros, pontos=[p])
                blocos.append(atual)
    return blocos


def dividir_bloco(bloco: Bloco) -> list[Bloco]:
    """Um bloco por ponto (usado quando o medidor recusa o bloco inteiro)."""
    return [Bloco(funcao=bloco.funcao, inicio=p.endereco, quantidade=p.n_registros, pontos=[p]) for p in bloco.pontos]
