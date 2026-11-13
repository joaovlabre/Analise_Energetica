"""Gerador de valores sintéticos para os escravos simulados.

Os valores são gerados na unidade canônica do mapa (V, A, kW, kWh...) e convertidos
para o valor bruto do medidor dividindo pela escala do mapa. Pontos com escala
A_VERIFICAR ficam zerados (não sabemos o que o medidor real entrega).
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from coletor.decodificador import codificar
from coletor.mapa import Ponto


@dataclass
class EstadoEletrico:
    """Estado de um medidor simulado: carga senoidal + totalizadores."""

    potencia_base_kw: float = 80.0
    potencia_variacao_kw: float = 30.0
    periodo_s: float = 600.0
    fp: float = 0.92
    tensao_fn: float = 220.0
    energia_ativa_kwh: float = 1_234_567.0
    energia_reativa_kvarh: float = 456_789.0
    energia_aparente_kvah: float = 1_350_000.0
    acelerar: float = 1.0  # multiplica o incremento dos totalizadores (testes rápidos de 15 min)
    ruido: float = 0.005
    t0: float = field(default_factory=time.monotonic)
    _t_ultimo: float | None = None
    pico_kw: float = 0.0

    def avancar(self, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        if self._t_ultimo is not None:
            dt_h = (agora - self._t_ultimo) / 3600.0 * self.acelerar
            p = self.potencia_kw(agora)
            q = p * math.tan(math.acos(self.fp))
            self.energia_ativa_kwh += p * dt_h
            self.energia_reativa_kvarh += q * dt_h
            self.energia_aparente_kvah += (p / self.fp) * dt_h
            self.pico_kw = max(self.pico_kw, p)
        self._t_ultimo = agora

    def resetar_totalizadores(self) -> None:
        self.energia_ativa_kwh = 0.0
        self.energia_reativa_kvarh = 0.0
        self.energia_aparente_kvah = 0.0

    def _r(self) -> float:
        return 1 + random.uniform(-self.ruido, self.ruido)

    def potencia_kw(self, agora: float | None = None) -> float:
        agora = time.monotonic() if agora is None else agora
        fase = 2 * math.pi * (agora - self.t0) / self.periodo_s
        return self.potencia_base_kw + self.potencia_variacao_kw * math.sin(fase)

    def valor(self, grandeza: str) -> float | None:
        """Valor canônico de uma grandeza, ou None se o simulador não sabe gerá-la."""
        p = self.potencia_kw()
        q = p * math.tan(math.acos(self.fp))
        s = p / self.fp
        vff = self.tensao_fn * math.sqrt(3)
        i = s * 1000 / (math.sqrt(3) * vff)
        g = grandeza
        if g in ("tensao_an", "tensao_bn", "tensao_cn", "tensao_fn_media"):
            return self.tensao_fn * self._r()
        if g in ("tensao_ab", "tensao_bc", "tensao_ca", "tensao_ff_media"):
            return vff * self._r()
        if g in ("corrente_a", "corrente_b", "corrente_c", "corrente_media"):
            return i * self._r()
        if g == "corrente_n":
            return 0.03 * i * self._r()
        if g.startswith("potencia_ativa"):
            return p if g.endswith("total") else p / 3 * self._r()
        if g.startswith("potencia_reativa"):
            return q if g.endswith("total") else q / 3 * self._r()
        if g.startswith("potencia_aparente"):
            return s if g.endswith("total") else s / 3 * self._r()
        if g.startswith("fp_caracteristica"):
            return 1.0  # indutivo
        if g.startswith("fp_"):
            return self.fp
        if g == "frequencia":
            return 60.0 + random.uniform(-0.02, 0.02)
        if g.startswith("demanda_ativa"):
            return self.pico_kw if g.endswith("pico") else p
        if g.startswith("demanda_reativa"):
            return q
        if g.startswith("demanda_aparente"):
            return s
        if g.startswith("energia_ativa_importada") or g in ("energia_ativa_liquida", "energia_ativa_bruta"):
            return self.energia_ativa_kwh
        if g.startswith("energia_ativa_exportada"):
            return 0.0
        if g.startswith("energia_reativa") and ("exp" in g or "q2" in g or "capacitiva" in g):
            return 0.0
        if g.startswith("energia_reativa"):
            return self.energia_reativa_kvarh
        if g.startswith("energia_aparente"):
            return self.energia_aparente_kvah
        if g.startswith("thd_tensao"):
            return 2.5 * self._r()
        if g.startswith("thd_corrente"):
            return 8.0 * self._r()
        if g.startswith("desequilibrio"):
            return 0.6 * self._r()
        if g.startswith("carregamento"):
            return 60.0 * self._r()
        if g == "timestamp_medidor":
            return float(int(time.time()))
        if g in ("tempo_operacao", "horas_carga_permanente"):
            return float(int(time.monotonic() - self.t0) + 3_600_000)
        if g == "numero_serie":
            return 123456.0
        if g == "falhas_alimentacao":
            return 3.0
        if g == "tp_primario" or g == "tp_secundario":
            return 380.0
        if g == "tc_primario":
            return 200.0
        if g == "tc_secundario":
            return 5.0
        return None


def gerar_registros(pontos: list[Ponto], estado: EstadoEletrico) -> dict[int, dict[int, int]]:
    """Gera {funcao: {endereco_protocolo: registrador}} para todos os pontos do mapa."""
    tabela: dict[int, dict[int, int]] = {}
    for p in pontos:
        destino = tabela.setdefault(p.funcao, {})
        valor = estado.valor(p.grandeza) if p.utilizavel else None
        if valor is None or p.tipo == "BIT":
            regs = [0] * p.n_registros
        else:
            bruto = valor / p.escala if p.escala else valor
            if p.tipo == "FLOAT32_4Q_PF":
                bruto = valor  # FP indutivo no 1º quadrante: codificação igual ao valor
            regs = codificar(bruto, p.tipo, p.word_order)
        for k, r in enumerate(regs):
            destino[p.endereco + k] = r
    return tabela
