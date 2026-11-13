"""Sobe escravos Modbus simulados para testar o coletor sem hardware.

Exemplos:
  python -m tests.simulador
  python -m tests.simulador --porta 5020 --acelerar 60 --queda 120:45 --reset 300
  python -m tests.simulador --escravo 1:config/mapas/weg_mmw02.csv --estrito

Padrão: escravo 1 = WEG MMW02, escravo 2 = Schneider EM3261, em 127.0.0.1:5020 (Modbus TCP).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from coletor.mapa import carregar_mapa
from tests.simulador.modelo import EstadoEletrico
from tests.simulador.servidor import EscravoSimulado, Falhas, ServidorSimulado

RAIZ = Path(__file__).resolve().parents[2]
PADRAO = [
    f"1:{RAIZ / 'config/mapas/weg_mmw02.csv'}",
    f"2:{RAIZ / 'config/mapas/schneider_gologic_em3261.csv'}",
]


def _par(txt: str) -> tuple[float, float]:
    a, b = txt.split(":")
    return float(a), float(b)


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador Modbus do SGE")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=5020)
    ap.add_argument("--quadro", choices=["tcp", "rtu_over_tcp"], default="tcp")
    ap.add_argument("--escravo", action="append", help="ID:caminho_do_mapa.csv (pode repetir)")
    ap.add_argument("--acelerar", type=float, default=1.0, help="multiplica o crescimento dos totalizadores")
    ap.add_argument("--estrito", action="store_true", help="exceção 02 ao ler endereço não mapeado")
    ap.add_argument("--queda", action="append", default=[], type=_par, help="INICIO_S:DURACAO_S sem responder")
    ap.add_argument("--reset", action="append", default=[], type=float, help="instante (s) para zerar totalizadores")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    escravos = []
    for item in args.escravo or PADRAO:
        uid, _, caminho = item.partition(":")
        escravos.append(
            EscravoSimulado(
                unidade=int(uid),
                pontos=carregar_mapa(caminho),
                estado=EstadoEletrico(acelerar=args.acelerar),
                estrito=args.estrito,
            )
        )
    servidor = ServidorSimulado(
        escravos, host=args.host, porta=args.porta, quadro=args.quadro, falhas=Falhas(quedas=args.queda, resets=args.reset)
    )

    async def rodar():
        await servidor.iniciar()
        try:
            await asyncio.Event().wait()
        finally:
            await servidor.parar()

    try:
        asyncio.run(rodar())
    except KeyboardInterrupt:
        print("simulador encerrado")
    except OSError as e:
        raise SystemExit(f"não foi possível abrir {args.host}:{args.porta} ({e}). Outro simulador já está rodando?")


if __name__ == "__main__":
    main()
