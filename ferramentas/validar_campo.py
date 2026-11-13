"""Validação do mapa em campo (SOMENTE LEITURA).

Lê cada ponto do mapa individualmente (inclusive A_VERIFICAR e grupo config), mostra os
registradores brutos e o valor decodificado nas 4 ordens de word, e gera um Excel com
colunas vazias para anotar o valor do display do medidor.

  python -m ferramentas.validar_campo --config config/local/dispositivos.yaml --dispositivo MED_01
  python -m ferramentas.validar_campo --config config/dispositivos.simulador.yaml --dispositivo SIM_WEG_MMW02

Depois de conferir: marcar `verificado = sim` no CSV e corrigir escala/word_order se preciso.
"""
from __future__ import annotations

import argparse
import asyncio
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from coletor.decodificador import WORD_ORDERS, aplicar_escala, decodificar
from coletor.mapa import Ponto, carregar_mapa
from coletor.transporte import ClienteModbus, ErroComunicacao, ErroExcecaoModbus
from comum.config import carregar_config
from comum.tempo import FUSO_EXIBICAO

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Resultado:
    ponto: Ponto
    regs: list[int] | None
    erro: str | None
    valores: dict[str, float | None]  # word_order -> valor (com escala, se conhecida)

    @property
    def valor_mapa(self) -> float | None:
        return self.valores.get(self.ponto.word_order)


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if abs(v) >= 1e7 or (v != 0 and abs(v) < 1e-3):
        return f"{v:.6g}"
    return f"{v:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


async def ler_todos(cliente: ClienteModbus, unidade: int, pontos: list[Ponto]) -> list[Resultado]:
    saida = []
    for p in pontos:
        try:
            regs = await cliente.ler(p.funcao, p.endereco, p.n_registros, unidade)
        except ErroExcecaoModbus as e:
            saida.append(Resultado(p, None, f"exceção {e.codigo:02d}", {}))
            continue
        except ErroComunicacao as e:
            saida.append(Resultado(p, None, f"sem resposta: {e}", {}))
            continue
        valores = {}
        for wo in WORD_ORDERS:
            try:
                bruto = decodificar(regs, p.tipo, wo) if p.tipo != "BIT" else regs[0]
                valores[wo] = aplicar_escala(bruto, p.escala) if p.escala is not None else float(bruto)
            except Exception:
                valores[wo] = None
        saida.append(Resultado(p, regs, None, valores))
    return saida


def imprimir(resultados: list[Resultado]) -> None:
    print(f"\n{'grandeza':34s} {'reg':>6s} {'FC':>2s} {'tipo':14s} {'registros (hex)':22s} {'valor (mapa)':>18s} unid  verif.")
    print("-" * 120)
    for r in resultados:
        p = r.ponto
        if r.erro:
            print(f"{p.grandeza:34s} {p.endereco_manual:>6d} {p.funcao:02d} {p.tipo:14s} {'':22s} {'ERRO: ' + r.erro:>18s}")
            continue
        hexa = " ".join(f"{x:04X}" for x in r.regs)
        unid = p.unidade if p.unidade is not None else "A_VERIFICAR"
        marca = "" if p.utilizavel else "  <- escala A_VERIFICAR (valor bruto)"
        print(f"{p.grandeza:34s} {p.endereco_manual:>6d} {p.funcao:02d} {p.tipo:14s} {hexa:22s} {_fmt(r.valor_mapa):>18s} {unid:5s} "
              f"{'sim' if p.verificado else 'não'}{marca}")


def gerar_excel(resultados: list[Resultado], destino: Path, cabecalho: dict[str, str]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Validação"
    linha = 1
    for k, v in cabecalho.items():
        ws.cell(linha, 1, k).font = Font(bold=True)
        ws.cell(linha, 2, v)
        linha += 1
    linha += 1
    colunas = ["Grandeza", "Descrição", "FC", "Registro (manual)", "Base", "Endereço protocolo", "Tipo", "Word order (mapa)",
               "Escala", "Unidade", "Registros (hex)", "Valor lido (mapa)",
               "Alt. ABCD", "Alt. CDAB", "Alt. BADC", "Alt. DCBA",
               "VALOR NO DISPLAY", "CONFERE? (sim/não)", "Observação de campo", "Obs. do mapa", "Verificado (mapa)"]
    destaque = PatternFill("solid", fgColor="FFF2CC")
    for j, c in enumerate(colunas, 1):
        cel = ws.cell(linha, j, c)
        cel.font = Font(bold=True)
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        if c in ("VALOR NO DISPLAY", "CONFERE? (sim/não)", "Observação de campo"):
            cel.fill = destaque
    ws.freeze_panes = ws.cell(linha + 1, 2)
    for r in resultados:
        linha += 1
        p = r.ponto
        vals = [p.grandeza, p.descricao, p.funcao, p.endereco_manual, p.base, p.endereco, p.tipo, p.word_order,
                p.escala if p.escala is not None else "A_VERIFICAR", p.unidade if p.unidade is not None else "A_VERIFICAR",
                " ".join(f"{x:04X}" for x in r.regs) if r.regs else r.erro,
                r.valor_mapa,
                *(r.valores.get(wo) for wo in WORD_ORDERS),
                None, None, None, p.obs, "sim" if p.verificado else "não"]
        for j, v in enumerate(vals, 1):
            if isinstance(v, float) and not math.isfinite(v):
                v = str(v)
            cel = ws.cell(linha, j, v)
            if colunas[j - 1] in ("VALOR NO DISPLAY", "CONFERE? (sim/não)", "Observação de campo"):
                cel.fill = destaque
    larguras = [30, 36, 5, 10, 6, 10, 14, 10, 10, 10, 24, 16, 14, 14, 14, 14, 18, 12, 30, 40, 10]
    for j, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


async def executar(args) -> None:
    cfg = carregar_config(args.config)
    disp = cfg.dispositivo(args.dispositivo)
    bar = cfg.barramento(disp.barramento)
    pontos = carregar_mapa(disp.mapa)
    if args.grupo:
        pontos = [p for p in pontos if p.grupo in args.grupo]
    onde = bar.porta if bar.tipo == "serial" else f"{bar.host}:{bar.porta_tcp}"
    print(f"Validando {disp.nome} ({disp.modelo}) via {bar.nome} [{onde}] ID {disp.endereco_modbus}: {len(pontos)} pontos")
    cliente = ClienteModbus(bar)
    try:
        resultados = await ler_todos(cliente, disp.endereco_modbus, pontos)
    finally:
        cliente.fechar()
    imprimir(resultados)
    agora = datetime.now(FUSO_EXIBICAO)
    erros = sum(1 for r in resultados if r.erro)
    cabecalho = {
        "Dispositivo": disp.nome,
        "Modelo": disp.modelo,
        "Mapa": Path(disp.mapa).name,
        "Comunicação": f"{bar.tipo} {onde} ID {disp.endereco_modbus}" + (f" {bar.baudrate} 8{bar.paridade}{bar.bits_parada}" if bar.tipo == "serial" else ""),
        "Data/hora da leitura": agora.strftime("%d/%m/%Y %H:%M:%S"),
        "Pontos lidos / com erro": f"{len(resultados) - erros} / {erros}",
        "Instrução": "Anote o valor do display na coluna amarela no mesmo instante. Valores instantâneos variam: compare a ordem de grandeza e a casa decimal.",
    }
    destino = Path(args.saida or RAIZ / "relatorios" / "saida") / f"validacao_{disp.nome}_{agora:%Y%m%d_%H%M%S}.xlsx"
    gerar_excel(resultados, destino, cabecalho)
    print(f"\n{len(resultados) - erros} ponto(s) lido(s), {erros} com erro. Planilha: {destino}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera planilha de validação de mapa em campo (somente leitura)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--dispositivo", required=True)
    ap.add_argument("--grupo", action="append", help="limita a grupos (pode repetir): instantaneo, energia, ...")
    ap.add_argument("--saida", help="pasta de saída (padrão: relatorios/saida)")
    args = ap.parse_args()
    asyncio.run(executar(args))


if __name__ == "__main__":
    main()
