"""Fluxo principal de coleta.

  python -m coletor --config config/local/dispositivos.yaml
  python -m coletor --config config/dispositivos.simulador.yaml --debug
  python -m coletor --config ... --duracao 300     # roda 5 min e sai (testes)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from armazenamento.esquema import criar_engine, criar_tabelas
from armazenamento.gravador import sincronizar_dispositivos
from coletor.servico import Coletor
from comum.config import carregar_config
from comum.log import configurar_log

log = logging.getLogger("coletor")


async def rodar(caminho_config: str, duracao: float | None) -> None:
    cfg = carregar_config(caminho_config)
    engine = criar_engine(cfg.banco.url)
    criar_tabelas(engine)
    ids = sincronizar_dispositivos(engine, cfg)
    coletor = Coletor(cfg, engine, ids)
    for c in coletor.dispositivos:
        b = cfg.barramento(c.cfg_disp.barramento)
        onde = b.porta if b.tipo == "serial" else f"{b.host}:{b.porta_tcp}"
        log.info("dispositivo %s (%s) via %s [%s] id %d: %d pontos", c.cfg_disp.nome, c.cfg_disp.modelo, b.nome, onde,
                 c.cfg_disp.endereco_modbus, len(c.pontos))
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, parar.set)
    except NotImplementedError:
        pass  # Windows: Ctrl+C gera KeyboardInterrupt
    if duracao:
        loop.call_later(duracao, parar.set)
    log.info("coleta iniciada (banco: %s)", cfg.banco.url)
    await coletor.executar(parar)
    log.info("coleta encerrada")


def main() -> None:
    ap = argparse.ArgumentParser(description="Coletor Modbus do SGE (somente leitura)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--debug", action="store_true", help="mostra bytes TX/RX e registradores decodificados")
    ap.add_argument("--duracao", type=float, help="segundos até parar automaticamente")
    args = ap.parse_args()
    configurar_log("coletor.log", debug=args.debug)
    try:
        asyncio.run(rodar(args.config, args.duracao))
    except KeyboardInterrupt:
        log.info("interrompido pelo usuário")


if __name__ == "__main__":
    main()
