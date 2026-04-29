"""Pastas de dados: mesma regra no Windows e Linux (XDG com variáveis padrão)."""

from __future__ import annotations

import os
import pathlib
import platform


def _xdg_data_home() -> pathlib.Path:
    v = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if v:
        return pathlib.Path(v).expanduser().resolve()
    return pathlib.Path.home() / ".local" / "share"


def data_root() -> pathlib.Path:
    """Raiz de dados (modelos, cache, gravações no futuro)."""
    o = (os.environ.get("NEOVISION_DATA_DIR") or "").strip()
    if o:
        return pathlib.Path(o).expanduser().resolve()
    if platform.system() == "Windows":
        la = (os.environ.get("LOCALAPPDATA") or "").strip()
        if la:
            return pathlib.Path(la) / "NeoVision"
        return pathlib.Path.home() / "AppData" / "Local" / "NeoVision"
    return _xdg_data_home() / "NeoVision"


def recordings_dir() -> pathlib.Path:
    """Onde o serviço gravará vídeo/clipes (diretório criado no arranque)."""
    return data_root() / "recordings"
