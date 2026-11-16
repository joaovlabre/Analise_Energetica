"""Diagramas unifilares definidos em YAML (fase atual: montados em configuração, sem editor).

Nada de potência, tensão ou medidor fixo no código: tudo vem do arquivo do diagrama.
Valor desconhecido fica nulo e aparece como "a definir" na tela.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from comum.config import Config


class MedidorDiagrama(BaseModel):
    dispositivo: str  # nome do dispositivo em dispositivos.yaml
    icone: Literal["schneider_em3261", "weg_mmw02", "generico"] = "generico"
    grandeza: str = "potencia_ativa_total"
    unidade_exibicao: str | None = None  # ex.: W (converte de kW só na tela); o valor fica sempre ao lado do ícone


class Transformador(BaseModel):
    nome: str
    potencia_kva: float | None = None
    tensao_primaria_kv: float | None = None
    tensao_secundaria_kv: float | None = None
    medidor: MedidorDiagrama | None = None


class Barra(BaseModel):
    nome: str
    tensao_kv: float | None = None


class Diagrama(BaseModel):
    slug: str
    nome: str
    descricao: str | None = None
    entrada: str | None = None  # rótulo da alimentação da barra
    barra: Barra
    transformadores: list[Transformador] = Field(default_factory=list)


def carregar_diagramas(cfg: Config) -> list[Diagrama]:
    nomes = {d.nome for d in cfg.dispositivos}
    saida: list[Diagrama] = []
    for caminho in cfg.diagramas:
        with Path(caminho).open(encoding="utf-8") as f:
            d = Diagrama.model_validate(yaml.safe_load(f))
        for t in d.transformadores:
            if t.medidor and t.medidor.dispositivo not in nomes:
                raise ValueError(f"diagrama '{d.slug}': {t.nome} usa o medidor '{t.medidor.dispositivo}', que não está em dispositivos")
        if any(x.slug == d.slug for x in saida):
            raise ValueError(f"diagrama '{d.slug}' duplicado")
        saida.append(d)
    return saida
