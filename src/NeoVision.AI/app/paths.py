"""Raiz do pacote: código normal vs executável PyInstaller (sys._MEIPASS)."""

from __future__ import annotations

import pathlib
import sys


def package_root() -> pathlib.Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return pathlib.Path(getattr(sys, "_MEIPASS", "."))
    return pathlib.Path(__file__).resolve().parent.parent
