"""Decodificação de registradores Modbus (16 bits) em valores numéricos.

Convenção de word_order (para 2 registradores, bytes A B C D na ordem "natural" big-endian):
- ABCD: big-endian, words na ordem recebida (padrão Modbus)
- CDAB: words invertidas (word swap)
- BADC: bytes trocados dentro de cada word (byte swap)
- DCBA: tudo invertido (little-endian)
Para 4 registradores (64 bits) a regra é a mesma: CDAB inverte a ordem das words,
BADC troca os bytes de cada word, DCBA faz as duas coisas.
Para 1 registrador (16 bits): BADC/DCBA trocam os bytes; ABCD/CDAB não mudam nada.
"""
from __future__ import annotations

import math
import struct

TAMANHO = {
    "BIT": 1,
    "INT16": 1,
    "UINT16": 1,
    "INT32": 2,
    "UINT32": 2,
    "FLOAT32": 2,
    "FLOAT32_4Q_PF": 2,
    "INT64": 4,
    "UINT64": 4,
    "FLOAT64": 4,
}

FORMATO_STRUCT = {
    "INT16": ">h",
    "UINT16": ">H",
    "INT32": ">i",
    "UINT32": ">I",
    "FLOAT32": ">f",
    "FLOAT32_4Q_PF": ">f",
    "INT64": ">q",
    "UINT64": ">Q",
    "FLOAT64": ">d",
}

WORD_ORDERS = ("ABCD", "CDAB", "BADC", "DCBA")


class ErroDecodificacao(ValueError):
    pass


def _ordenar_words(registros: list[int], word_order: str) -> list[int]:
    if word_order not in WORD_ORDERS:
        raise ErroDecodificacao(f"word_order inválido: {word_order}")
    regs = list(registros)
    if word_order in ("CDAB", "DCBA"):
        regs.reverse()
    if word_order in ("BADC", "DCBA"):
        regs = [((r & 0xFF) << 8) | (r >> 8) for r in regs]
    return regs


def registros_para_bytes(registros: list[int], word_order: str) -> bytes:
    regs = _ordenar_words(registros, word_order)
    return b"".join(struct.pack(">H", r & 0xFFFF) for r in regs)


def decodificar_pf_4q(valor: float) -> float:
    """Fator de potência no formato 4 quadrantes da Schneider (tipo FLOAT32_4Q_PF).

    Codificação (conforme observação do mapa: '>1 ou <-1 = adiantado'):
      valor > 1  -> FP = 2 - valor
      valor < -1 -> FP = -2 - valor
      caso contrário -> FP = valor
    A conferência com a aba "Data Types" da lista de registradores da Schneider está pendente.
    """
    if valor > 1:
        return 2 - valor
    if valor < -1:
        return -2 - valor
    return valor


def decodificar(registros: list[int], tipo: str, word_order: str = "ABCD") -> float | int:
    """Converte registradores brutos para o valor na unidade do medidor (sem aplicar escala)."""
    if tipo not in FORMATO_STRUCT:
        raise ErroDecodificacao(f"tipo não suportado: {tipo}")
    n = TAMANHO[tipo]
    if len(registros) != n:
        raise ErroDecodificacao(f"{tipo} precisa de {n} registradores, recebeu {len(registros)}")
    dados = registros_para_bytes(registros, word_order)
    (valor,) = struct.unpack(FORMATO_STRUCT[tipo], dados)
    if tipo == "FLOAT32_4Q_PF" and math.isfinite(valor):
        valor = decodificar_pf_4q(valor)
    return valor


def aplicar_escala(valor: float | int, escala: float) -> float:
    return float(valor) * escala if escala != 1 else float(valor)


def codificar(valor: float | int, tipo: str, word_order: str = "ABCD") -> list[int]:
    """Inverso de `decodificar` (usado pelo simulador e pelos testes). Para FLOAT32_4Q_PF, `valor` é o bruto."""
    if tipo not in FORMATO_STRUCT:
        raise ErroDecodificacao(f"tipo não suportado: {tipo}")
    fmt = FORMATO_STRUCT[tipo]
    if fmt[-1] not in "fd":
        valor = int(round(valor))
    dados = struct.pack(fmt, valor)
    regs_naturais = [struct.unpack(">H", dados[i : i + 2])[0] for i in range(0, len(dados), 2)]
    # a transformação de word_order é uma involução: aplicar de novo desfaz
    return _ordenar_words(regs_naturais, word_order)
