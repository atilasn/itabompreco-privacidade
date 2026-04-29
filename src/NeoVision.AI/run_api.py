"""Ponto de entrada: `python run_api.py` (dev) e executável PyInstaller (pasta dist)."""

from __future__ import annotations

import os
import socket
import sys


def _free_port() -> int:
    for p in (8080, 9080, 10080):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
    return 8080


def main() -> None:
    if getattr(sys, "frozen", False):
        exedir = os.path.dirname(os.path.abspath(sys.executable))
        if exedir:
            os.chdir(exedir)

    raw = (os.environ.get("NEOVISION_API_PORT") or "").strip()
    if raw:
        try:
            port = int(raw)
        except ValueError:
            print("NEOVISION_API_PORT inválido; a usar porta livre 8080/9080.", file=sys.stderr)
            port = _free_port()
    else:
        port = _free_port()

    from uvicorn import run

    run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
