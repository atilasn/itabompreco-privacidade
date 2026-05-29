"""Raiz do pacote: código normal vs executável PyInstaller (sys._MEIPASS)."""

from __future__ import annotations

import pathlib
import sys


def package_root() -> pathlib.Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return pathlib.Path(getattr(sys, "_MEIPASS", "."))
    return pathlib.Path(__file__).resolve().parent.parent


def data_dir_writable() -> pathlib.Path:
    """Pasta gravável ao lado do exe (empacotado) ou ao lado da raiz da API em dev."""
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys.executable).resolve().parent
    else:
        base = package_root().parent.parent
    return base / "NeoVisionData"
