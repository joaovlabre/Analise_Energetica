"""Servidor da API e das telas web.

  python -m api --config config/dispositivos.simulador.yaml
  python -m api --config config/local/dispositivos.yaml
"""
from __future__ import annotations

import argparse

import uvicorn

from api.app import criar_app
from comum.config import carregar_config
from comum.log import configurar_log


def main() -> None:
    ap = argparse.ArgumentParser(description="API e interface web do SGE")
    ap.add_argument("--config", required=True)
    ap.add_argument("--host")
    ap.add_argument("--porta", type=int)
    args = ap.parse_args()
    configurar_log("api.log")
    cfg = carregar_config(args.config)
    uvicorn.run(criar_app(cfg), host=args.host or cfg.api.host, port=args.porta or cfg.api.porta, log_config=None)


if __name__ == "__main__":
    main()
