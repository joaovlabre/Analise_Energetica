"""Leitura dos mapas de registradores (config/mapas/*.csv).

Formato: grandeza,descricao,funcao,endereco,base,tipo,word_order,escala,unidade,grupo,verificado,obs
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from coletor.decodificador import TAMANHO, WORD_ORDERS

FUNCOES_LEITURA = {1, 2, 3, 4}  # somente leitura em campo (regra inviolável)
GRUPOS_VALIDOS = {"instantaneo", "energia", "demanda", "qualidade", "status", "config"}
MARCA_A_VERIFICAR = "A_VERIFICAR"


class ErroMapa(ValueError):
    pass


@dataclass(frozen=True)
class Ponto:
    grandeza: str
    descricao: str
    funcao: int
    endereco_manual: int
    base: int
    tipo: str
    word_order: str
    escala: float | None  # None = A_VERIFICAR
    unidade: str | None  # None = A_VERIFICAR; "" = adimensional
    grupo: str
    verificado: bool
    obs: str = ""

    @property
    def endereco(self) -> int:
        """Endereço no protocolo (base 0)."""
        return self.endereco_manual - self.base

    @property
    def n_registros(self) -> int:
        return TAMANHO[self.tipo]

    @property
    def fim(self) -> int:
        """Primeiro endereço após o ponto."""
        return self.endereco + self.n_registros

    @property
    def utilizavel(self) -> bool:
        """Pontos com escala/unidade A_VERIFICAR não entram no fluxo principal."""
        return self.escala is not None and self.unidade is not None


def _texto(v: str | None) -> str:
    return (v or "").strip()


def _ler_linha(linha: dict, n: int, arquivo: str) -> Ponto:
    ctx = f"{arquivo}, linha {n}"
    grandeza = _texto(linha.get("grandeza"))
    if not grandeza:
        raise ErroMapa(f"{ctx}: grandeza vazia")
    try:
        funcao = int(_texto(linha.get("funcao")))
    except ValueError as e:
        raise ErroMapa(f"{ctx}: função inválida") from e
    if funcao not in FUNCOES_LEITURA:
        raise ErroMapa(f"{ctx}: função {funcao:02d} não permitida (somente leitura: 01, 02, 03, 04)")
    try:
        endereco = int(_texto(linha.get("endereco")))
        base = int(_texto(linha.get("base")))
    except ValueError as e:
        raise ErroMapa(f"{ctx}: endereço/base inválido") from e
    if base not in (0, 1):
        raise ErroMapa(f"{ctx}: base deve ser 0 ou 1")
    if endereco - base < 0 or endereco - base > 65535:
        raise ErroMapa(f"{ctx}: endereço fora da faixa Modbus")
    tipo = _texto(linha.get("tipo")).upper()
    if tipo not in TAMANHO:
        raise ErroMapa(f"{ctx}: tipo desconhecido '{tipo}'")
    if funcao in (1, 2) and tipo != "BIT":
        raise ErroMapa(f"{ctx}: funções 01/02 exigem tipo BIT")
    if funcao in (3, 4) and tipo == "BIT":
        raise ErroMapa(f"{ctx}: tipo BIT exige função 01/02")
    word_order = _texto(linha.get("word_order")).upper() or "ABCD"
    if word_order not in WORD_ORDERS:
        raise ErroMapa(f"{ctx}: word_order inválido '{word_order}'")
    escala_txt = _texto(linha.get("escala"))
    if escala_txt.upper() == MARCA_A_VERIFICAR:
        escala = None
    else:
        try:
            escala = float(escala_txt.replace(",", ".")) if escala_txt else 1.0
        except ValueError as e:
            raise ErroMapa(f"{ctx}: escala inválida '{escala_txt}'") from e
    unidade_txt = _texto(linha.get("unidade"))
    unidade = None if unidade_txt.upper() == MARCA_A_VERIFICAR else unidade_txt
    grupo = _texto(linha.get("grupo"))
    if grupo not in GRUPOS_VALIDOS:
        raise ErroMapa(f"{ctx}: grupo inválido '{grupo}'")
    verificado = _texto(linha.get("verificado")).lower() == "sim"
    return Ponto(
        grandeza=grandeza,
        descricao=_texto(linha.get("descricao")),
        funcao=funcao,
        endereco_manual=endereco,
        base=base,
        tipo=tipo,
        word_order=word_order,
        escala=escala,
        unidade=unidade,
        grupo=grupo,
        verificado=verificado,
        obs=_texto(linha.get("obs")),
    )


def carregar_mapa(caminho: str | Path) -> list[Ponto]:
    caminho = Path(caminho)
    with caminho.open(encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f)
        pontos = [_ler_linha(linha, i + 2, caminho.name) for i, linha in enumerate(leitor)]
    nomes = [p.grandeza for p in pontos]
    duplicadas = {n for n in nomes if nomes.count(n) > 1}
    if duplicadas:
        raise ErroMapa(f"{caminho.name}: grandezas duplicadas: {sorted(duplicadas)}")
    # sobreposição de registradores na mesma função indica erro de digitação no mapa
    por_funcao: dict[int, list[Ponto]] = {}
    for p in pontos:
        por_funcao.setdefault(p.funcao, []).append(p)
    for lista in por_funcao.values():
        lista.sort(key=lambda p: p.endereco)
        for a, b in zip(lista, lista[1:]):
            if b.endereco < a.fim:
                raise ErroMapa(f"{caminho.name}: '{a.grandeza}' e '{b.grandeza}' se sobrepõem")
    return pontos
