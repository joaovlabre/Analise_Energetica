"""Sobe escravos Modbus simulados para testar o coletor sem hardware.

Exemplos:
  python -m tests.simulador
  python -m tests.simulador --porta 5020 --acelerar 60 --queda 120:45 --reset 300
  python -m tests.simulador --queda-medidor 2:60:30      # medidor ID 2 fora por 30 s (gateway responde 0B)
  python -m tests.simulador --escravo 1:config/mapas/weg_mmw02.csv --estrito

Padrão: simula um GATEWAY RS485/TCP em 127.0.0.1:5020 (Modbus TCP) com dois medidores em série
atrás dele: ID 1 = WEG MMW02, ID 2 = Schneider EM3261.
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


def _trio(txt: str) -> tuple[int, float, float]:
    a, b, c = txt.split(":")
    return int(a), float(b), float(c)


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulador Modbus do SGE")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--porta", type=int, default=5020)
    ap.add_argument("--quadro", choices=["tcp", "rtu_over_tcp"], default="tcp")
    ap.add_argument("--escravo", action="append", help="ID:caminho_do_mapa.csv (pode repetir)")
    ap.add_argument("--acelerar", type=float, default=1.0, help="multiplica o crescimento dos totalizadores")
    ap.add_argument("--estrito", action="store_true", help="exceção 02 ao ler endereço não mapeado")
    ap.add_argument("--queda", action="append", default=[], type=_par, help="INICIO_S:DURACAO_S gateway inteiro sem responder")
    ap.add_argument("--queda-medidor", action="append", default=[], type=_trio,
                    help="ID:INICIO_S:DURACAO_S só um medidor fora (gateway responde exceção 0B)")
    ap.add_argument("--sem-gateway", action="store_true", help="escravo ausente fica em silêncio (medidor com Ethernet nativa)")
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
        escravos, host=args.host, porta=args.porta, quadro=args.quadro, falhas=Falhas(quedas=args.queda, quedas_escravo=args.queda_medidor, resets=args.reset),
        gateway=not args.sem_gateway,
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
