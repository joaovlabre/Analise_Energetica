"""Descobre portas COM e parâmetros de comunicação de um medidor (SOMENTE LEITURA).

  python -m ferramentas.varrer_serial --listar
  python -m ferramentas.varrer_serial --porta COM3 --mapa config/mapas/weg_mmw02.csv
  python -m ferramentas.varrer_serial --porta COM3 --baud 9600,19200 --paridade N,E --ids 1-10 --leitura 4:0:2

Para cada combinação baud/paridade/ID envia UM pedido de leitura e mostra quem respondeu.
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import sys

from serial.tools import list_ports

from coletor.decodificador import aplicar_escala, decodificar
from coletor.mapa import carregar_mapa
from coletor.transporte import ClienteModbus, ErroComunicacao, ErroExcecaoModbus
from comum.config import Barramento


def _faixa_ids(txt: str) -> list[int]:
    ids: list[int] = []
    for parte in txt.split(","):
        if "-" in parte:
            a, b = parte.split("-")
            ids.extend(range(int(a), int(b) + 1))
        else:
            ids.append(int(parte))
    return ids


def listar() -> None:
    portas = list(list_ports.comports())
    if not portas:
        print("Nenhuma porta serial encontrada. Confira o driver do conversor USB-RS485.")
    for p in portas:
        print(f"{p.device:8s} {p.description}  [{p.hwid}]")


async def varrer(args) -> int:
    if args.mapa:
        ponto = next(p for p in carregar_mapa(args.mapa) if p.utilizavel and p.grupo == "instantaneo")
        funcao, endereco, qtd = ponto.funcao, ponto.endereco, ponto.n_registros
        print(f"Teste com '{ponto.grandeza}' (reg {ponto.endereco_manual}, FC{funcao:02d}, {ponto.tipo})")
    else:
        funcao, endereco, qtd = (int(x) for x in args.leitura.split(":"))
        ponto = None
    achados = 0
    for baud, paridade in itertools.product([int(b) for b in args.baud.split(",")], args.paridade.split(",")):
        b = Barramento(nome="varredura", tipo="serial", porta=args.porta, baudrate=baud, paridade=paridade,
                       timeout_s=args.timeout, retentativas=0, pausa_entre_pedidos_ms=0)
        cliente = ClienteModbus(b)
        try:
            await cliente.conectar()
        except ErroComunicacao as e:
            print(f"Não foi possível abrir {args.porta}: {e}")
            return 2
        for uid in _faixa_ids(args.ids):
            rotulo = f"{baud:>6} 8{paridade}1 id {uid:>3}"
            try:
                regs = await cliente.ler(funcao, endereco, qtd, uid)
                extra = ""
                if ponto:
                    v = decodificar(regs, ponto.tipo, ponto.word_order)
                    extra = f" -> {aplicar_escala(v, ponto.escala):.3f} {ponto.unidade}"
                print(f"{rotulo}: RESPONDEU  regs={' '.join(f'{r:04X}' for r in regs)}{extra}")
                achados += 1
            except ErroExcecaoModbus as e:
                print(f"{rotulo}: respondeu com exceção {e.codigo:02d} (há escravo nesse ID; endereço/função recusados)")
                achados += 1
            except ErroComunicacao:
                if args.verboso:
                    print(f"{rotulo}: sem resposta")
        cliente.fechar()
    print(f"\n{achados} resposta(s) encontrada(s).")
    return 0 if achados else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Varredura serial Modbus RTU (somente leitura)")
    ap.add_argument("--listar", action="store_true", help="lista as portas COM disponíveis")
    ap.add_argument("--porta", help="ex.: COM3")
    ap.add_argument("--baud", default="9600,19200")
    ap.add_argument("--paridade", default="N,E")
    ap.add_argument("--ids", default="1-10")
    ap.add_argument("--mapa", help="usa o primeiro ponto instantâneo do mapa como leitura de teste")
    ap.add_argument("--leitura", default="4:0:2", help="FC:endereço_protocolo:quantidade (se não usar --mapa)")
    ap.add_argument("--timeout", type=float, default=0.3)
    ap.add_argument("--verboso", action="store_true")
    args = ap.parse_args()
    if args.listar or not args.porta:
        listar()
        return
    sys.exit(asyncio.run(varrer(args)))


if __name__ == "__main__":
    main()
