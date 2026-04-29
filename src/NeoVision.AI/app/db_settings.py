"""Definição MySQL (alinhada ao Desktop: Server 127.0.0.1, base neovision, user neovision)."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
