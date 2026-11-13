"""Carga e validação da configuração (dispositivos.yaml).

Nada de endereço, IP, porta COM ou ID fixo no código: tudo vem do YAML.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

GRUPOS = ("instantaneo", "energia", "demanda", "qualidade", "status", "config")


class Barramento(BaseModel):
    """Um meio físico/lógico com UM mestre: uma porta serial ou uma conexão TCP com gateway/medidor."""

    nome: str
    tipo: Literal["serial", "tcp", "rtu_over_tcp"]
    # serial (modbus_rtu)
    porta: str | None = None  # ex.: COM3
    baudrate: int = 9600
    paridade: Literal["N", "E", "O"] = "N"
    bits_dados: int = 8
    bits_parada: int = 1
    # tcp (modbus_tcp) / rtu_over_tcp
    host: str | None = None
    porta_tcp: int = 502
    # comportamento
    timeout_s: float = 1.0
    retentativas: int = 2
    pausa_entre_pedidos_ms: int = 30

    @model_validator(mode="after")
    def _checar(self):
        if self.tipo == "serial" and not self.porta:
            raise ValueError(f"barramento '{self.nome}': tipo serial exige 'porta' (ex.: COM3)")
        if self.tipo in ("tcp", "rtu_over_tcp") and not self.host:
            raise ValueError(f"barramento '{self.nome}': tipo {self.tipo} exige 'host'")
        return self

    @property
    def origem(self) -> str:
        return "modbus_rtu" if self.tipo in ("serial", "rtu_over_tcp") else "modbus_tcp"


class TaxaGrupo(BaseModel):
    leitura_s: float  # frequência de leitura (tela / valor atual)
    gravacao_s: float  # frequência de gravação no histórico (tabela leitura)


class Faixa(BaseModel):
    minimo: float
    maximo: float


class Dispositivo(BaseModel):
    nome: str
    modelo: str
    barramento: str
    endereco_modbus: int = Field(ge=1, le=247)
    mapa: str
    ativo: bool = True
    grupos: list[str] = Field(default_factory=lambda: ["instantaneo", "energia", "demanda", "qualidade", "status"])
    max_registros_por_pedido: int = Field(default=60, ge=1, le=125)
    max_buraco: int = Field(default=6, ge=0)  # registradores não mapeados tolerados dentro de um mesmo pedido
    local: str | None = None  # descrição do ponto de instalação (QGBT, CCM...)


class Coleta(BaseModel):
    ciclo_base_s: float = 1.0
    taxas: dict[str, TaxaGrupo]
    faixas: dict[str, Faixa] = Field(default_factory=dict)  # chave = prefixo da grandeza (ex.: "tensao_")


class Agregacao(BaseModel):
    intervalo_min: int = 15
    grandezas: list[str] = Field(default_factory=lambda: ["energia_ativa_importada"])
    max_lacuna_min: float = 5.0  # acima disso, o consumo recuperado é marcado 'estimado'
    periodo_execucao_s: float = 60.0


class Banco(BaseModel):
    url: str = "sqlite:///dados/sge.db"


class Api(BaseModel):
    host: str = "127.0.0.1"
    porta: int = 8000


class Config(BaseModel):
    banco: Banco = Field(default_factory=Banco)
    api: Api = Field(default_factory=Api)
    coleta: Coleta
    agregacao: Agregacao = Field(default_factory=Agregacao)
    barramentos: list[Barramento]
    dispositivos: list[Dispositivo]

    @model_validator(mode="after")
    def _checar(self):
        nomes_bar = {b.nome for b in self.barramentos}
        if len(nomes_bar) != len(self.barramentos):
            raise ValueError("nomes de barramento duplicados")
        nomes_disp = [d.nome for d in self.dispositivos]
        if len(set(nomes_disp)) != len(nomes_disp):
            raise ValueError("nomes de dispositivo duplicados")
        vistos: set[tuple[str, int]] = set()
        for d in self.dispositivos:
            if d.barramento not in nomes_bar:
                raise ValueError(f"dispositivo '{d.nome}': barramento '{d.barramento}' não existe")
            chave = (d.barramento, d.endereco_modbus)
            if d.ativo and chave in vistos:
                raise ValueError(f"dispositivo '{d.nome}': endereço Modbus {d.endereco_modbus} repetido no barramento")
            vistos.add(chave)
            for g in d.grupos:
                if g not in GRUPOS:
                    raise ValueError(f"dispositivo '{d.nome}': grupo desconhecido '{g}'")
                if g not in self.coleta.taxas:
                    raise ValueError(f"dispositivo '{d.nome}': grupo '{g}' sem taxa em coleta.taxas")
        return self

    def barramento(self, nome: str) -> Barramento:
        return next(b for b in self.barramentos if b.nome == nome)

    def dispositivo(self, nome: str) -> Dispositivo:
        for d in self.dispositivos:
            if d.nome == nome:
                return d
        raise KeyError(f"dispositivo '{nome}' não está na configuração")


def carregar_config(caminho: str | Path, raiz: str | Path | None = None) -> Config:
    """Lê o YAML. Caminhos relativos de mapa são resolvidos a partir de `raiz` (padrão: pasta do projeto)."""
    caminho = Path(caminho)
    with caminho.open(encoding="utf-8") as f:
        dados = yaml.safe_load(f)
    cfg = Config.model_validate(dados)
    raiz = Path(raiz) if raiz else Path(__file__).resolve().parent.parent
    for d in cfg.dispositivos:
        p = Path(d.mapa)
        if not p.is_absolute():
            d.mapa = str((raiz / p).resolve())
    return cfg
