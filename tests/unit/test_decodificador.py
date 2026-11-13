import math
import struct

import pytest

from coletor.decodificador import ErroDecodificacao, codificar, decodificar, decodificar_pf_4q


def regs_float32(valor: float) -> list[int]:
    b = struct.pack(">f", valor)
    return [int.from_bytes(b[0:2], "big"), int.from_bytes(b[2:4], "big")]


def test_float32_abcd_vetor_conhecido():
    # 220.5 em IEEE754 = 0x435C8000
    assert decodificar([0x435C, 0x8000], "FLOAT32", "ABCD") == pytest.approx(220.5)


@pytest.mark.parametrize(
    "regs,ordem",
    [
        ([0x435C, 0x8000], "ABCD"),
        ([0x8000, 0x435C], "CDAB"),
        ([0x5C43, 0x0080], "BADC"),
        ([0x0080, 0x5C43], "DCBA"),
    ],
)
def test_float32_quatro_word_orders(regs, ordem):
    assert decodificar(regs, "FLOAT32", ordem) == pytest.approx(220.5)


def test_int64_abcd():
    # 123456789012 Wh = 0x0000001CBE991A14
    assert decodificar([0x0000, 0x001C, 0xBE99, 0x1A14], "INT64", "ABCD") == 123456789012


def test_int64_cdab_inverte_words():
    assert decodificar([0x1A14, 0xBE99, 0x001C, 0x0000], "INT64", "CDAB") == 123456789012


def test_int64_negativo():
    assert decodificar([0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF], "INT64") == -1


def test_uint32_e_int16():
    assert decodificar([0x0001, 0x0000], "UINT32") == 65536
    assert decodificar([0xFFFF], "INT16") == -1
    assert decodificar([0xFFFF], "UINT16") == 65535
    assert decodificar([0x3412], "UINT16", "BADC") == 0x1234


def test_nan_preservado():
    assert math.isnan(decodificar([0xFFC0, 0x0000], "FLOAT32"))


def test_quantidade_errada():
    with pytest.raises(ErroDecodificacao):
        decodificar([1], "FLOAT32")


@pytest.mark.parametrize("tipo", ["INT16", "UINT16", "INT32", "UINT32", "FLOAT32", "INT64", "UINT64", "FLOAT64"])
@pytest.mark.parametrize("ordem", ["ABCD", "CDAB", "BADC", "DCBA"])
def test_ida_e_volta(tipo, ordem):
    valor = 1234 if "INT" in tipo else 1234.5
    assert decodificar(codificar(valor, tipo, ordem), tipo, ordem) == pytest.approx(valor)


@pytest.mark.parametrize(
    "bruto,esperado",
    [(0.9, 0.9), (-0.8, -0.8), (1.1, 0.9), (-1.2, -0.8), (1.0, 1.0)],
)
def test_pf_4q(bruto, esperado):
    assert decodificar_pf_4q(bruto) == pytest.approx(esperado)


def test_pf_4q_via_registros():
    assert decodificar(regs_float32(1.1), "FLOAT32_4Q_PF") == pytest.approx(0.9, abs=1e-6)
