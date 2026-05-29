"""Equipamentos na rede por IP — ping ICMP ou verificação HTTP opcional, estado Online/Offline."""

from __future__ import annotations

import json
import platform
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.camera_ids import dotnet_bytes_to_uuid, uuid_to_dotnet_bytes
from app.db_settings import DatabaseSettings


EXTRAS_JSON_UNCHANGED = object()

ICON_KIND_ALLOWED = frozenset(
    {
        "generic",
        "switch",
        "router",
        "camera",
        "wifi",
        "server",
        "firewall",
        "printer",
        "nas",
        "access_point",
        "site",
    },
)


def normalize_icon_kind(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    return s if s in ICON_KIND_ALLOWED else "generic"


def normalize_hub_scope(raw: str | None) -> str:
    s = (raw or "local").strip().lower()
    return s if s in ("local", "online") else "local"


@dataclass(frozen=True)
class NetworkEquipmentRow:
    id: str
    label: str
    ip_address: str
    poll_interval_seconds: int
    is_enabled: bool
    icon_kind: str
    extras_json: str | None
    last_state: bool | None
    last_check_utc: str | None
    state_since_utc: str | None
    total_up_seconds: int
    total_down_seconds: int
    offline_incidents: int = 0
    monitor_hub_scope: str = "local"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_dt(s: Any) -> datetime | None:
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    t = str(s).strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _row_from_db(r: dict[str, Any]) -> NetworkEquipmentRow:
    raw_id = r["id"]
    if not isinstance(raw_id, (bytes, bytearray, memoryview)):
        raise TypeError("network_equipment_hosts.id formato inesperado")
    uid = dotnet_bytes_to_uuid(bytes(raw_id))
    label = (r.get("label") or "").strip()[:128] or "—"
    ip = (r.get("ip_address") or "").strip()[:253] or "0.0.0.0"
    poll = int(r.get("poll_interval_seconds") or 60)
    poll = max(10, min(86400, poll))
    en = r.get("is_enabled")
    is_en = True if en is None else bool(int(en)) if not isinstance(en, bool) else en
    ls = r.get("last_state")
    if ls is None:
        last_st: bool | None = None
    else:
        last_st = bool(int(ls)) if not isinstance(ls, bool) else bool(ls)
    last_iso = r.get("last_check_utc")
    last_check = None if last_iso is None else str(last_iso).strip() or None
    since_iso = r.get("state_since_utc")
    state_since = None if since_iso is None else str(since_iso).strip() or None
    tup = int(r.get("total_up_seconds") or 0)
    tdn = int(r.get("total_down_seconds") or 0)
    ik = normalize_icon_kind(r.get("icon_kind"))
    ex_raw = r.get("extras_json")
    extras_txt: str | None
    if ex_raw is None:
        extras_txt = None
    elif isinstance(ex_raw, (dict, list)):
        extras_txt = json.dumps(ex_raw, ensure_ascii=False)[:8192]
    else:
        t = str(ex_raw).strip()
        extras_txt = t[:8192] if t else None
    oi = int(r.get("offline_incidents") or 0)
    mhs = normalize_hub_scope(r.get("monitor_hub_scope"))
    return NetworkEquipmentRow(
        id=str(uid),
        label=label,
        ip_address=ip,
        poll_interval_seconds=poll,
        is_enabled=is_en,
        icon_kind=ik,
        extras_json=extras_txt,
        last_state=last_st,
        last_check_utc=last_check,
        state_since_utc=state_since,
        total_up_seconds=max(0, tup),
        total_down_seconds=max(0, tdn),
        offline_incidents=max(0, oi),
        monitor_hub_scope=mhs,
    )


_SQLITE_DDLS = """
CREATE TABLE IF NOT EXISTS network_equipment_hosts (
    id                      BLOB NOT NULL PRIMARY KEY,
    label                   TEXT NOT NULL DEFAULT '',
    ip_address              TEXT NOT NULL,
    poll_interval_seconds   INTEGER NOT NULL DEFAULT 60,
    is_enabled              INTEGER NOT NULL DEFAULT 1,
    icon_kind               TEXT NOT NULL DEFAULT 'generic',
    extras_json             TEXT NULL,
    last_state              INTEGER NULL,
    last_check_utc          TEXT NULL,
    state_since_utc         TEXT NULL,
    total_up_seconds        INTEGER NOT NULL DEFAULT 0,
    total_down_seconds      INTEGER NOT NULL DEFAULT 0,
    offline_incidents       INTEGER NOT NULL DEFAULT 0,
    monitor_hub_scope       TEXT NOT NULL DEFAULT 'local',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at              TEXT NULL
);
"""


def _migrate_sqlite_icon_kind(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA table_info(network_equipment_hosts)").fetchall()
    names = [r[1] for r in row] if row else []
    if "icon_kind" not in names:
        conn.execute(
            "ALTER TABLE network_equipment_hosts ADD COLUMN icon_kind TEXT NOT NULL DEFAULT 'generic'"
        )


def _migrate_sqlite_extras_json(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA table_info(network_equipment_hosts)").fetchall()
    names = [r[1] for r in row] if row else []
    if "extras_json" not in names:
        conn.execute(
            "ALTER TABLE network_equipment_hosts ADD COLUMN extras_json TEXT NULL"
        )


def _migrate_sqlite_offline_incidents(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA table_info(network_equipment_hosts)").fetchall()
    names = [r[1] for r in row] if row else []
    if "offline_incidents" not in names:
        conn.execute(
            "ALTER TABLE network_equipment_hosts ADD COLUMN offline_incidents INTEGER NOT NULL DEFAULT 0"
        )


def _migrate_sqlite_monitor_hub_scope(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA table_info(network_equipment_hosts)").fetchall()
    names = [r[1] for r in row] if row else []
    if not names:
        return
    if "monitor_hub_scope" not in names:
        conn.execute(
            "ALTER TABLE network_equipment_hosts ADD COLUMN monitor_hub_scope TEXT NOT NULL DEFAULT 'local'"
        )


def _ensure_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=30.0)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SQLITE_DDLS)
        _migrate_sqlite_icon_kind(conn)
        _migrate_sqlite_extras_json(conn)
        _migrate_sqlite_offline_incidents(conn)
        _migrate_sqlite_monitor_hub_scope(conn)
        conn.commit()


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    _ensure_sqlite(path)
    return sqlite3.connect(str(path), timeout=30.0)


def _connect_mysql(settings: Any) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


_mysql_table_done: set[str] = set()
_mysql_alter_ip_hostname: set[str] = set()


def _migrate_mysql_ip_length(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"w:{settings.mysql.host}:{settings.mysql.database}"
    if key in _mysql_alter_ip_hostname:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT CHARACTER_MAXIMUM_LENGTH AS n
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'network_equipment_hosts'
                      AND COLUMN_NAME = 'ip_address'
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                n = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if n > 0 and n < 253:
                    cur.execute(
                        "ALTER TABLE network_equipment_hosts MODIFY ip_address VARCHAR(253) NOT NULL"
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_alter_ip_hostname.add(key)


_mysql_icon_kind_done: set[str] = set()


def _migrate_mysql_icon_kind(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"icon:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_icon_kind_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'network_equipment_hosts'
                      AND COLUMN_NAME = 'icon_kind'
                    """
                )
                row = cur.fetchone()
                n = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if n < 1:
                    cur.execute(
                        """
                        ALTER TABLE network_equipment_hosts
                            ADD COLUMN icon_kind VARCHAR(32) NOT NULL DEFAULT 'generic'
                        """
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_icon_kind_done.add(key)


def _ensure_mysql_table(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key not in _mysql_table_done:
        sql = """
        CREATE TABLE IF NOT EXISTS network_equipment_hosts (
            id                      BINARY(16) NOT NULL PRIMARY KEY,
            label                   VARCHAR(128) NOT NULL DEFAULT '',
            ip_address              VARCHAR(253) NOT NULL,
            poll_interval_seconds   INT UNSIGNED NOT NULL DEFAULT 60,
            is_enabled              TINYINT(1) NOT NULL DEFAULT 1,
            icon_kind               VARCHAR(32) NOT NULL DEFAULT 'generic',
            extras_json             TEXT NULL,
            last_state              TINYINT(1) NULL,
            last_check_utc          DATETIME(3) NULL,
            state_since_utc         DATETIME(3) NULL,
            total_up_seconds        BIGINT UNSIGNED NOT NULL DEFAULT 0,
            total_down_seconds      BIGINT UNSIGNED NOT NULL DEFAULT 0,
            offline_incidents       INT UNSIGNED NOT NULL DEFAULT 0,
            monitor_hub_scope       VARCHAR(16) NOT NULL DEFAULT 'local',
            created_at              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
            updated_at              DATETIME(3) NULL ON UPDATE CURRENT_TIMESTAMP(3),
            KEY ix_net_eq_ip (ip_address),
            KEY ix_net_eq_en (is_enabled)
        ) ENGINE=InnoDB;
    """
        with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
            cur.execute(sql)
        _mysql_table_done.add(key)
    _migrate_mysql_ip_length(settings)
    _migrate_mysql_icon_kind(settings)
    _migrate_mysql_extras_json(settings)
    _migrate_mysql_offline_incidents(settings)
    _migrate_mysql_monitor_hub_scope(settings)


_mysql_offline_incidents_done: set[str] = set()
_mysql_monitor_hub_scope_done: set[str] = set()


def _migrate_mysql_monitor_hub_scope(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"mhs:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_monitor_hub_scope_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'network_equipment_hosts'
                      AND COLUMN_NAME = 'monitor_hub_scope'
                    """
                )
                row = cur.fetchone()
                n = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if n < 1:
                    cur.execute(
                        """
                        ALTER TABLE network_equipment_hosts
                            ADD COLUMN monitor_hub_scope VARCHAR(16) NOT NULL DEFAULT 'local'
                        """
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_monitor_hub_scope_done.add(key)




def _migrate_mysql_offline_incidents(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"oi:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_offline_incidents_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'network_equipment_hosts'
                      AND COLUMN_NAME = 'offline_incidents'
                    """
                )
                row = cur.fetchone()
                n = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if n < 1:
                    cur.execute(
                        """
                        ALTER TABLE network_equipment_hosts
                            ADD COLUMN offline_incidents INT UNSIGNED NOT NULL DEFAULT 0
                        """
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_offline_incidents_done.add(key)


_mysql_extras_done: set[str] = set()


def _migrate_mysql_extras_json(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"extras:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_extras_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'network_equipment_hosts'
                      AND COLUMN_NAME = 'extras_json'
                    """
                )
                row = cur.fetchone()
                n = int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if n < 1:
                    cur.execute(
                        """
                        ALTER TABLE network_equipment_hosts
                            ADD COLUMN extras_json TEXT NULL
                        """
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_extras_done.add(key)


def db_ping_error(settings: DatabaseSettings) -> str | None:
    try:
        if settings.backend == "sqlite":
            assert settings.sqlite_path is not None
            with closing(_connect_sqlite(settings.sqlite_path)) as conn:
                conn.execute("SELECT 1")
            return None
        assert settings.mysql is not None
        with closing(_connect_mysql(settings.mysql)) as conn:
            conn.ping()
    except (sqlite3.Error, OSError) as e:
        return str(e)
    except pymysql.Error as e:
        return str(e)
    return None


def ping_icmp(ip: str, timeout_ms: int = 2500) -> bool:
    """True se o host respondeu ao ping (ICMP)."""
    t = (ip or "").strip()
    if not t:
        return False
    timeout_ms = max(500, min(10000, int(timeout_ms)))
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), t],
                capture_output=True,
                timeout=max(3.5, timeout_ms / 1000 + 2.5),
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,  # type: ignore[attr-defined]
            )
            raw = proc.stdout + proc.stderr
            try:
                out = raw.decode("cp437")
            except UnicodeDecodeError:
                out = raw.decode("utf-8", errors="replace")
        else:
            sec = max(1, (timeout_ms + 999) // 1000)
            proc = subprocess.run(
                ["ping", "-c", "1", "-W", str(sec), t],
                capture_output=True,
                timeout=max(3.5, sec + 2.0),
            )
            out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return False
    lo = out.lower()
    if "ttl=" in lo:
        return True
    if platform.system() != "Windows" and ("bytes from" in lo or "icmp_seq" in lo):
        return True
    return False


def ping_http_url(url: str, timeout_sec: float = 4.5) -> bool:
    """True se o URL responde com código HTTP 2xx/3xx (GET, segue redirecções)."""
    t = (url or "").strip()
    if not t or len(t) > 2048:
        return False
    if not t.lower().startswith(("http://", "https://")):
        t = "http://" + t
    try:
        req = urllib.request.Request(
            t,
            headers={"User-Agent": "NeoVision-NetworkMonitor/1.0"},
        )
        ctx = ssl.create_default_context()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        with opener.open(req, timeout=max(1.0, float(timeout_sec))) as resp:
            code = resp.getcode()
            return 200 <= int(code) < 400
    except urllib.error.HTTPError as e:
        if e.code is not None and 200 <= int(e.code) < 400:
            return True
        # Resposta 401/403 indica serviço a escutar (equipamento "ligado"), só não autorizado.
        if e.code is not None and int(e.code) in (401, 403):
            return True
        return False
    except Exception:
        return False


def http_monitor_url_from_extras(extras_json: str | None) -> str | None:
    d = parse_extras_dict(extras_json)
    u = d.get("http_monitor_url")
    if u is None:
        return None
    s = str(u).strip()
    return s[:2048] if s else None


def set_http_monitor_in_extras(existing_json: str | None, url: str | None) -> str | None:
    """Guarda ou remove ``http_monitor_url`` no JSON de extras (não altera painel_dvr)."""
    root = parse_extras_dict(existing_json)
    if url is None:
        root.pop("http_monitor_url", None)
    else:
        s = str(url).strip()
        if s:
            root["http_monitor_url"] = _truncate(s, 2048)
        else:
            root.pop("http_monitor_url", None)
    return serialize_extras_blob(root)


def list_hosts(settings: DatabaseSettings, hub_scope: str | None = None) -> list[NetworkEquipmentRow]:
    _ensure_mysql_table(settings)
    sql_base = """
        SELECT
            id, label, ip_address, poll_interval_seconds, is_enabled,
            icon_kind, extras_json,
            last_state, last_check_utc, state_since_utc,
            total_up_seconds, total_down_seconds, offline_incidents,
            monitor_hub_scope
        FROM network_equipment_hosts
    """
    params: tuple[Any, ...] = ()
    if hub_scope is not None and str(hub_scope).strip():
        sql = sql_base + " WHERE monitor_hub_scope = ? ORDER BY label, ip_address"
        params = (normalize_hub_scope(hub_scope),)
    else:
        sql = sql_base + " ORDER BY label, ip_address"
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
    else:
        assert settings.mysql is not None
        sql_m = sql.replace("?", "%s")
        with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
            if params:
                cur.execute(sql_m, params)
            else:
                cur.execute(sql_m)
            rows = [dict(r) for r in cur.fetchall()]
    return [_row_from_db(r) for r in rows]


def get_host(settings: DatabaseSettings, id_str: str) -> NetworkEquipmentRow | None:
    from uuid import UUID

    _ensure_mysql_table(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    sql = """
        SELECT
            id, label, ip_address, poll_interval_seconds, is_enabled,
            icon_kind, extras_json,
            last_state, last_check_utc, state_since_utc,
            total_up_seconds, total_down_seconds, offline_incidents,
            monitor_hub_scope
        FROM network_equipment_hosts
        WHERE id = ?
        LIMIT 1
    """
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, (bin_id,))
            r = cur.fetchone()
        if r is None:
            return None
        return _row_from_db(dict(r))

    assert settings.mysql is not None
    sql_m = sql.replace("?", "%s")
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(sql_m, (bin_id,))
        r = cur.fetchone()
    if r is None:
        return None
    return _row_from_db(dict(r))


def _truncate(s: str, n: int) -> str:
    t = s.strip()
    return t[:n] if len(t) > n else t


def normalize_monitor_target(raw: str) -> str:
    t = raw.strip()
    if not (1 <= len(t) <= 253):
        raise ValueError("indique um IP ou hostname válido (1–253 caracteres)")
    try:
        import ipaddress

        ipaddress.ip_address(t)
        return t
    except ValueError:
        if "/" in t or "\n" in t or "\r" in t or " " in t:
            msg = "use apenas IPv4/v6 válido ou um nome DNS simples para o equipamento"
            raise ValueError(msg) from None
        return t[:253]


def parse_extras_dict(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        o = json.loads(raw)
        return o if isinstance(o, dict) else {}
    except json.JSONDecodeError:
        return {}


def serialize_extras_blob(root: dict[str, Any]) -> str | None:
    if not root:
        return None
    s = json.dumps(root, ensure_ascii=False)
    if len(s) > 8192:
        msg = "metadados (extras_json) ultrapassam 8192 caracteres"
        raise ValueError(msg)
    return s


def merge_network_extras_dvr_panel(existing_json: str | None, patch: dict[str, Any]) -> str | None:
    """Altera apenas chaves presentes em ``patch``: ``url``, ``usuario``, ``senha`` (texto ou vazio para limpar)."""
    root = parse_extras_dict(existing_json)
    if not patch:
        return serialize_extras_blob(root)

    dvr_prev: dict[str, Any] = dict(
        root.get("painel_dvr") if isinstance(root.get("painel_dvr"), dict) else {}
    )

    def _upd_str(key_patch: str, key_store: str, max_len: int) -> None:
        if key_patch not in patch:
            return
        raw = patch[key_patch]
        t = "" if raw is None else str(raw).strip()
        if not t:
            dvr_prev.pop(key_store, None)
        else:
            dvr_prev[key_store] = _truncate(t, max_len)

    _upd_str("url", "url", 512)
    _upd_str("usuario", "usuario", 128)
    _upd_str("senha", "senha", 256)

    if dvr_prev:
        root["painel_dvr"] = dvr_prev
    else:
        root.pop("painel_dvr", None)

    return serialize_extras_blob(root)


def dvr_painel_campos_desde_extras(extras_json: str | None) -> dict[str, str | None]:
    """Extrai campos devolvidos na API ao painel (senha só em rede local NeoVision)."""
    d = parse_extras_dict(extras_json)
    nest = d.get("painel_dvr") if isinstance(d.get("painel_dvr"), dict) else {}
    u_url = nest.get("url")
    u_usuario = nest.get("usuario")
    u_senha = nest.get("senha")
    pw: str | None
    if u_senha is None:
        pw = None
    else:
        pt = str(u_senha)[:256]
        pw = pt if pt.strip() else None
    return {
        "url_painel_dvr": (str(u_url).strip()[:512] if u_url else None) or None,
        "usuario_painel_dvr": (str(u_usuario).strip()[:128] if u_usuario else None) or None,
        "senha_painel_dvr": pw,
    }


def insert_host(
    settings: DatabaseSettings,
    *,
    label: str,
    ip_address: str,
    poll_interval_seconds: int,
    is_enabled: bool,
    icon_kind: str | None = None,
    extras_json: str | None = None,
    monitor_hub_scope: str | None = None,
) -> str:
    ip = normalize_monitor_target(ip_address)
    poll = max(10, min(86400, int(poll_interval_seconds)))
    lb = _truncate(label, 128) or "Equipamento"
    ik = normalize_icon_kind(icon_kind)
    mhs = normalize_hub_scope(monitor_hub_scope)
    new_id = uuid.uuid4()
    bin_id = uuid_to_dotnet_bytes(new_id)
    now = _iso_now()
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        _ensure_sqlite(settings.sqlite_path)
        sql = """
            INSERT INTO network_equipment_hosts
                (id, label, ip_address, poll_interval_seconds, is_enabled,
                 icon_kind,
                 extras_json,
                 last_state, last_check_utc, state_since_utc,
                 total_up_seconds, total_down_seconds, offline_incidents,
                 monitor_hub_scope,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, 0, ?, ?, ?)
        """
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.execute(
                sql,
                (
                    bin_id,
                    lb,
                    _truncate(ip, 253),
                    poll,
                    1 if is_enabled else 0,
                    ik,
                    extras_json,
                    mhs,
                    now,
                    now,
                ),
            )
            conn.commit()
        return str(new_id)

    assert settings.mysql is not None
    sql_mysql = """
        INSERT INTO network_equipment_hosts
            (id, label, ip_address, poll_interval_seconds, is_enabled,
             icon_kind,
             extras_json,
             last_state, last_check_utc, state_since_utc,
             total_up_seconds, total_down_seconds, offline_incidents,
             monitor_hub_scope,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, 0, 0, 0, %s, UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))
    """
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(
            sql_mysql,
            (
                bin_id,
                lb,
                _truncate(ip, 253),
                poll,
                1 if is_enabled else 0,
                ik,
                extras_json,
                mhs,
            ),
        )
        conn.commit()
    return str(new_id)


def update_host(
    settings: DatabaseSettings,
    id_str: str,
    *,
    label: str,
    ip_address: str,
    poll_interval_seconds: int,
    is_enabled: bool,
    icon_kind: str | None = None,
    extras_json: Any = EXTRAS_JSON_UNCHANGED,
    monitor_hub_scope: str | None = None,
) -> bool:
    from uuid import UUID

    _ensure_mysql_table(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    ip = normalize_monitor_target(ip_address)
    poll = max(10, min(86400, int(poll_interval_seconds)))
    lb = _truncate(label, 128) or "Equipamento"
    ik = normalize_icon_kind(icon_kind)
    now = _iso_now()
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        sets = ["label = ?", "ip_address = ?", "poll_interval_seconds = ?", "is_enabled = ?", "icon_kind = ?"]
        params: list[Any] = [
            lb,
            _truncate(ip, 253),
            poll,
            1 if is_enabled else 0,
            ik,
        ]
        if extras_json is not EXTRAS_JSON_UNCHANGED:
            sets.append("extras_json = ?")
            params.append(extras_json)
        if monitor_hub_scope is not None:
            sets.append("monitor_hub_scope = ?")
            params.append(normalize_hub_scope(monitor_hub_scope))
        sets.append("updated_at = ?")
        params.append(now)
        params.append(bin_id)

        sql = "UPDATE network_equipment_hosts SET " + ", ".join(sets) + " WHERE id = ?"

        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            return cur.rowcount == 1

    assert settings.mysql is not None
    sets_mysql = ["label=%s", "ip_address=%s", "poll_interval_seconds=%s", "is_enabled=%s", "icon_kind=%s"]
    params_m: list[Any] = [lb, _truncate(ip, 253), poll, 1 if is_enabled else 0, ik]
    if extras_json is not EXTRAS_JSON_UNCHANGED:
        sets_mysql.append("extras_json=%s")
        params_m.append(extras_json)
    if monitor_hub_scope is not None:
        sets_mysql.append("monitor_hub_scope=%s")
        params_m.append(normalize_hub_scope(monitor_hub_scope))
    sets_mysql.append("updated_at=UTC_TIMESTAMP(3)")
    params_m.append(bin_id)
    sql_mysql = "UPDATE network_equipment_hosts SET " + ", ".join(sets_mysql) + " WHERE id=%s"

    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(sql_mysql, tuple(params_m))
        conn.commit()
        return cur.rowcount == 1


def delete_host(settings: DatabaseSettings, id_str: str) -> bool:
    from uuid import UUID

    _ensure_mysql_table(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute("DELETE FROM network_equipment_hosts WHERE id = ?", (bin_id,))
            conn.commit()
            return cur.rowcount == 1

    assert settings.mysql is not None
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM network_equipment_hosts WHERE id = %s", (bin_id,))
        conn.commit()
        return cur.rowcount == 1


def delete_all_hosts(settings: DatabaseSettings) -> int:
    """Remove todos os registos de monitorização de rede (para import em máquina nova)."""
    _ensure_mysql_table(settings)
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute("DELETE FROM network_equipment_hosts")
            conn.commit()
            return int(cur.rowcount or 0)

    assert settings.mysql is not None
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM network_equipment_hosts")
        conn.commit()
        return int(cur.rowcount or 0)


def _find_id_bin_by_ip_and_scope(
    settings: DatabaseSettings, ip_normalized: str, hub_scope: str
) -> bytes | None:
    ip_st = _truncate(ip_normalized, 253)
    sc = normalize_hub_scope(hub_scope)
    sql = "SELECT id FROM network_equipment_hosts WHERE ip_address = ? AND monitor_hub_scope = ? LIMIT 1"
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute(sql, (ip_st, sc))
            r = cur.fetchone()
        if r is None:
            return None
        return bytes(r[0])

    assert settings.mysql is not None
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(sql.replace("?", "%s"), (ip_st, sc))
        r = cur.fetchone()
        if r is None or r.get("id") is None:
            return None
        return bytes(r["id"])


def backup_rows_for_export(settings: DatabaseSettings) -> list[dict[str, Any]]:
    """Lista de dicionários prontos para JSON (sem ids nem tempos acumulados)."""
    rows = list_hosts(settings)
    out: list[dict[str, Any]] = []
    for r in rows:
        dvr = dvr_painel_campos_desde_extras(r.extras_json)
        out.append(
            {
                "nome": r.label,
                "ip_address": r.ip_address,
                "poll_interval_seconds": int(r.poll_interval_seconds),
                "is_enabled": bool(r.is_enabled),
                "icon_kind": r.icon_kind,
                "url_painel_dvr": dvr.get("url_painel_dvr"),
                "usuario_painel_dvr": dvr.get("usuario_painel_dvr"),
                "senha_painel_dvr": dvr.get("senha_painel_dvr"),
                "http_monitor_url": http_monitor_url_from_extras(r.extras_json),
                "monitor_hub_scope": r.monitor_hub_scope,
            }
        )
    return out


def import_backup_rows(
    settings: DatabaseSettings,
    items: list[dict[str, Any]],
    *,
    replace_all: bool,
) -> dict[str, int]:
    """
    Importa lista de hosts. Se replace_all, apaga todos antes.
    Caso contrário: mesmo ip_address → update; senão insert.
    """

    def _dvr_patch_from_raw(raw: dict[str, Any]) -> dict[str, Any] | None:
        keys = ("url_painel_dvr", "usuario_painel_dvr", "senha_painel_dvr")
        if not any(k in raw for k in keys):
            return None
        patch: dict[str, Any] = {}
        for k_json, k_raw in (
            ("url", "url_painel_dvr"),
            ("usuario", "usuario_painel_dvr"),
            ("senha", "senha_painel_dvr"),
        ):
            if k_raw in raw:
                patch[k_json] = raw[k_raw]
        return patch

    if len(items) > 2048:
        raise ValueError("no máximo 2048 equipamentos por backup.")
    if replace_all:
        delete_all_hosts(settings)

    ins = 0
    upd = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        nome = _truncate(str(raw.get("nome") or "Equipamento"), 128) or "Equipamento"
        ip = str(raw.get("ip_address") or "").strip()
        if not ip:
            continue
        try:
            ip_ok = normalize_monitor_target(ip)
        except ValueError:
            continue
        poll = int(raw.get("poll_interval_seconds") or 60)
        en = raw.get("is_enabled")
        is_en = True if en is None else bool(en)
        ik = normalize_icon_kind(str(raw.get("icon_kind") or "generic"))
        row_scope = normalize_hub_scope(raw.get("monitor_hub_scope"))
        dvr_patch = _dvr_patch_from_raw(raw)
        ej_new: str | None = (
            merge_network_extras_dvr_panel(None, dvr_patch) if dvr_patch is not None else None
        )
        if "http_monitor_url" in raw:
            ej_new = set_http_monitor_in_extras(ej_new, raw.get("http_monitor_url"))

        if not replace_all:
            exist = _find_id_bin_by_ip_and_scope(settings, ip_ok, row_scope)
            if exist is not None:
                uid = str(dotnet_bytes_to_uuid(exist))
                extras_arg: Any = EXTRAS_JSON_UNCHANGED
                if dvr_patch is not None or "http_monitor_url" in raw:
                    cur_h = get_host(settings, uid)
                    ej_base = cur_h.extras_json if cur_h else None
                    extras_arg = ej_base
                    if dvr_patch is not None:
                        extras_arg = merge_network_extras_dvr_panel(extras_arg, dvr_patch)
                    if "http_monitor_url" in raw:
                        extras_arg = set_http_monitor_in_extras(extras_arg, raw.get("http_monitor_url"))
                if update_host(
                    settings,
                    uid,
                    label=nome,
                    ip_address=ip_ok,
                    poll_interval_seconds=poll,
                    is_enabled=is_en,
                    icon_kind=ik,
                    extras_json=extras_arg,
                    monitor_hub_scope=row_scope,
                ):
                    upd += 1
                continue

        insert_host(
            settings,
            label=nome,
            ip_address=ip_ok,
            poll_interval_seconds=poll,
            is_enabled=is_en,
            icon_kind=ik,
            extras_json=ej_new,
            monitor_hub_scope=row_scope,
        )
        ins += 1

    return {"inserted": ins, "updated": upd, "replaced_all": int(bool(replace_all))}


def record_ping_and_accumulate(settings: DatabaseSettings, host_id_bin: bytes, *, is_up: bool) -> None:
    """Actualiza estado após ping; acumula tempo do segmento só quando o estado muda."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="milliseconds")

    sql_sel = """
        SELECT last_state, state_since_utc, total_up_seconds, total_down_seconds,
               COALESCE(offline_incidents, 0) AS offline_incidents
        FROM network_equipment_hosts
        WHERE id = ?
        LIMIT 1
    """

    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql_sel, (host_id_bin,))
            row = cur.fetchone()
            if row is None:
                return
            d = dict(row)
    else:
        assert settings.mysql is not None
        with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
            cur.execute(sql_sel.replace("?", "%s"), (host_id_bin,))
            d = cur.fetchone()
            if d is None:
                return

    ls_raw = d.get("last_state")
    tup = int(d.get("total_up_seconds") or 0)
    tdn = int(d.get("total_down_seconds") or 0)
    oi = int(d.get("offline_incidents") or 0)
    since_dt = _parse_dt(d.get("state_since_utc"))

    prev: bool | None
    if ls_raw is None:
        prev = None
    elif isinstance(ls_raw, bool):
        prev = ls_raw
    else:
        prev = bool(int(ls_raw))

    if prev is None:
        if settings.backend == "sqlite":
            assert settings.sqlite_path is not None
            with closing(_connect_sqlite(settings.sqlite_path)) as conn:
                conn.execute(
                    """
                    UPDATE network_equipment_hosts SET
                        last_state = ?,
                        last_check_utc = ?,
                        state_since_utc = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        1 if is_up else 0,
                        now_iso,
                        now_iso,
                        now_iso,
                        host_id_bin,
                    ),
                )
                conn.commit()
        else:
            assert settings.mysql is not None
            with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE network_equipment_hosts SET
                        last_state = %s,
                        last_check_utc = %s,
                        state_since_utc = %s,
                        updated_at = UTC_TIMESTAMP(3)
                    WHERE id = %s
                    """,
                    (1 if is_up else 0, now_iso, since_dt or now, host_id_bin),
                )
                conn.commit()
        return

    if prev == is_up:
        if settings.backend == "sqlite":
            assert settings.sqlite_path is not None
            with closing(_connect_sqlite(settings.sqlite_path)) as conn:
                conn.execute(
                    """
                    UPDATE network_equipment_hosts SET
                        last_check_utc = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, host_id_bin),
                )
                conn.commit()
        else:
            assert settings.mysql is not None
            with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE network_equipment_hosts SET
                        last_check_utc = %s,
                        updated_at = UTC_TIMESTAMP(3)
                    WHERE id = %s
                    """,
                    (now_iso, host_id_bin),
                )
                conn.commit()
        return

    since_seg = since_dt or now
    delta = max(0, int((now - since_seg).total_seconds()))
    new_tup = tup + (delta if prev else 0)
    new_tdn = tdn + (delta if not prev else 0)
    new_oi = oi + (1 if prev is True and not is_up else 0)

    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.execute(
                """
                UPDATE network_equipment_hosts SET
                    last_state = ?,
                    last_check_utc = ?,
                    state_since_utc = ?,
                    total_up_seconds = ?,
                    total_down_seconds = ?,
                    offline_incidents = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if is_up else 0,
                    now_iso,
                    now_iso,
                    new_tup,
                    new_tdn,
                    new_oi,
                    now_iso,
                    host_id_bin,
                ),
            )
            conn.commit()
    else:
        assert settings.mysql is not None
        with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE network_equipment_hosts SET
                    last_state = %s,
                    last_check_utc = %s,
                    state_since_utc = %s,
                    total_up_seconds = %s,
                    total_down_seconds = %s,
                    offline_incidents = %s,
                    updated_at = UTC_TIMESTAMP(3)
                WHERE id = %s
                """,
                (1 if is_up else 0, now_iso, now, new_tup, new_tdn, new_oi, host_id_bin),
            )
            conn.commit()


def apply_simple_ping_row(settings: DatabaseSettings, row: NetworkEquipmentRow) -> None:
    """ICMP ou pedido HTTP conforme ``extras_json.http_monitor_url``."""
    from uuid import UUID

    u = UUID(row.id)
    bin_id = uuid_to_dotnet_bytes(u)
    h_url = http_monitor_url_from_extras(row.extras_json)
    if h_url:
        up = ping_http_url(h_url)
    else:
        up = ping_icmp(row.ip_address)
    record_ping_and_accumulate(settings, bin_id, is_up=up)


def check_due_hosts(settings: DatabaseSettings) -> None:
    """Verifica apenas anfitriões activos cujo intervalo já decorreu."""
    rows = list_hosts(settings)
    now = datetime.now(timezone.utc)
    for row in rows:
        if not row.is_enabled:
            continue
        lc = _parse_dt(row.last_check_utc)
        if lc is not None:
            elapsed = (now - lc).total_seconds()
            if elapsed < float(row.poll_interval_seconds):
                continue
        apply_simple_ping_row(settings, row)


async def monitor_loop(interval_sec: float = 5.0) -> None:
    """Tarefa de fundo: verifica IPs conforme intervalo configurado por equipamento."""
    import asyncio

    from app.db_settings import DatabaseSettings

    while True:
        await asyncio.sleep(max(2.0, interval_sec))
        try:
            settings = DatabaseSettings.from_environ()
            err = db_ping_error(settings)
            if err:
                continue
            await asyncio.to_thread(check_due_hosts, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue
