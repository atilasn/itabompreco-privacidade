"""Configuração da base de dados: SQLite (por defeito) ou MySQL (opcional).

Variáveis de ambiente relevantes::

  NEOVISION_DB — ``sqlite`` (padrão) ou ``mysql``
  NEOVISION_SQLITE_PATH — caminho do ficheiro .sqlite (senão NeoVisionData/neovision.sqlite)
  Para MySQL: NEOVISION_MYSQL_* (tal como antes)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _e(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v if v else default


@dataclass(frozen=True)
class MysqlSettings:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_environ(cls) -> MysqlSettings:
        return cls(
            host=_e("NEOVISION_MYSQL_HOST", "127.0.0.1"),
            port=int(_e("NEOVISION_MYSQL_PORT", "3306")),
            user=_e("NEOVISION_MYSQL_USER", "neovision"),
            password=_e("NEOVISION_MYSQL_PASSWORD", "changeme"),
            database=_e("NEOVISION_MYSQL_DATABASE", "neovision"),
        )


BackendKind = Literal["sqlite", "mysql"]


@dataclass(frozen=True)
class DatabaseSettings:
    """Definições unificadas: um backend ativo."""

    backend: BackendKind
    sqlite_path: Path | None
    mysql: MysqlSettings | None

    @classmethod
    def from_environ(cls) -> DatabaseSettings:
        raw = (_e("NEOVISION_DB", "sqlite") or "").lower().strip()
        if raw in ("mysql", "mariadb"):
            return cls(
                backend="mysql",
                sqlite_path=None,
                mysql=MysqlSettings.from_environ(),
            )
        sqlite_path = _sqlite_path_from_environ()
        return cls(
            backend="sqlite",
            sqlite_path=sqlite_path,
            mysql=None,
        )


def _sqlite_path_from_environ() -> Path:
    from app.paths import data_dir_writable

    hint = os.environ.get("NEOVISION_SQLITE_PATH", "").strip()
    if hint:
        return Path(hint).expanduser().resolve()
    dd = data_dir_writable()
    return (dd / "neovision.sqlite").resolve()
