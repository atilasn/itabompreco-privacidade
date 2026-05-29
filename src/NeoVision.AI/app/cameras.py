"""Câmeras: leitura/escrita em SQLite ou MySQL (tabela `cameras`) e teste RTSP (OpenCV)."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.camera_ids import dotnet_bytes_to_uuid, uuid_to_dotnet_bytes
from app.db_settings import DatabaseSettings, MysqlSettings


def _normalize_hub_scope_cam(raw: str | None) -> str:
    s = (raw or "local").strip().lower()
    return s if s in ("local", "online") else "local"


@dataclass(frozen=True)
class CameraRow:
    id: str
    name: str
    ip_address: str
    http_port: int | None
    rtsp_url: str | None
    onvif_endpoint: str | None
    is_enabled: bool
    last_seen_utc: str | None
    manufacturer: str | None = None
    model: str | None = None
    extras_json: str | None = None
    offline_incidents: int = 0
    last_rtsp_probe_ok: bool | None = None
    monitor_hub_scope: str = "local"


def _parse_last_seen(ls: Any) -> str | None:
    """MySQL DATETIME ou SQLite TEXT compatível ISO."""
    if ls is None:
        return None
    if isinstance(ls, datetime):
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        return ls.astimezone(timezone.utc).isoformat()
    if isinstance(ls, date):
        return datetime.combine(ls, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    if isinstance(ls, str):
        t = ls.strip()
        if not t:
            return None
        try:
            norm = t.replace("Z", "+00:00")
            if " " in norm and "T" not in norm.partition(" ")[0]:
                norm = norm.replace(" ", "T", 1)
            dt = datetime.fromisoformat(norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            return t
    return None


def _row_from_db(r: dict[str, Any]) -> CameraRow:
    raw_id = r["id"]
    if not isinstance(raw_id, (bytes, bytearray, memoryview)):
        msg = "coluna id em formato inesperado"
        raise TypeError(msg)
    uid = dotnet_bytes_to_uuid(bytes(raw_id))
    name = (r.get("name") or "").strip() or "—"
    ip = (r.get("ip_address") or "").strip() or "0.0.0.0"
    h = r.get("http_port")
    port = None if h is None else int(h)
    rt = r.get("rtsp_url")
    rtsp = None if rt is None or (isinstance(rt, str) and not rt.strip()) else str(rt)
    onv = r.get("onvif_endpoint")
    onvif = None if onv is None or (isinstance(onv, str) and not onv.strip()) else str(onv)
    en = r.get("is_enabled")
    if en is None:
        is_en = True
    elif isinstance(en, (bytes, memoryview)):
        raw = bytes(en)
        is_en = bool(raw[0]) if raw else True
    elif isinstance(en, (int, float)):
        is_en = bool(int(en))
    else:
        is_en = bool(en)
    last_iso = _parse_last_seen(r.get("last_seen_at"))
    mf_raw = r.get("manufacturer")
    md_raw = r.get("model")
    manufacturer = (
        None if mf_raw is None or (isinstance(mf_raw, str) and not mf_raw.strip()) else str(mf_raw).strip()[:64]
    )
    model = None if md_raw is None or (isinstance(md_raw, str) and not md_raw.strip()) else str(md_raw).strip()[:64]
    ex_raw = r.get("extras_json")
    extras_str: str | None
    if ex_raw is None:
        extras_str = None
    elif isinstance(ex_raw, (dict, list)):
        extras_str = json.dumps(ex_raw, ensure_ascii=False)
    else:
        extras_str = str(ex_raw).strip() or None
    return CameraRow(
        id=str(uid),
        name=name,
        ip_address=ip,
        http_port=port,
        rtsp_url=rtsp,
        onvif_endpoint=onvif,
        is_enabled=is_en,
        last_seen_utc=last_iso,
        manufacturer=manufacturer,
        model=model,
        extras_json=extras_str,
        offline_incidents=max(0, int(r.get("offline_incidents") or 0)),
        last_rtsp_probe_ok=(
            None
            if r.get("last_rtsp_probe_ok") is None
            else (
                bool(r["last_rtsp_probe_ok"])
                if isinstance(r.get("last_rtsp_probe_ok"), bool)
                else bool(int(r["last_rtsp_probe_ok"]))
            )
        ),
        monitor_hub_scope=_normalize_hub_scope_cam(r.get("monitor_hub_scope")),
    )


def _connect_mysql(settings: MysqlSettings) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


_SQLITE_DDLS = """
CREATE TABLE IF NOT EXISTS cameras (
    id              BLOB NOT NULL PRIMARY KEY,
    name            TEXT NOT NULL,
    manufacturer    TEXT NULL,
    model           TEXT NULL,
    ip_address      TEXT NOT NULL,
    http_port       INTEGER NULL,
    rtsp_url        TEXT NULL,
    onvif_endpoint  TEXT NULL,
    username        TEXT NULL,
    password_enc    BLOB NULL,
    is_enabled      INTEGER NOT NULL DEFAULT 1,
    last_seen_at    TEXT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NULL,
    extras_json     TEXT NULL,
    offline_incidents INTEGER NOT NULL DEFAULT 0,
    last_rtsp_probe_ok INTEGER NULL,
    monitor_hub_scope TEXT NOT NULL DEFAULT 'local'
);
"""


def _migrate_sqlite_cameras_hub_scope(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(cameras)")
    cols = {row[1] for row in cur.fetchall()}
    if not cols:
        return
    if "monitor_hub_scope" not in cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN monitor_hub_scope TEXT NOT NULL DEFAULT 'local'")


def _migrate_sqlite_cameras_probe(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(cameras)")
    cols = {row[1] for row in cur.fetchall()}
    if not cols:
        return
    if "offline_incidents" not in cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN offline_incidents INTEGER NOT NULL DEFAULT 0")
    if "last_rtsp_probe_ok" not in cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN last_rtsp_probe_ok INTEGER NULL")


def _migrate_sqlite_cameras_extra(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(cameras)")
    cols = {row[1] for row in cur.fetchall()}
    if not cols:
        return
    if "extras_json" not in cols:
        conn.execute("ALTER TABLE cameras ADD COLUMN extras_json TEXT NULL")


_mysql_extras_migration_done: set[str] = set()
_mysql_probe_migration_done: set[str] = set()
_mysql_cam_hub_scope_done: set[str] = set()


def _migrate_mysql_cameras_hub_scope(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"mhs:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_cam_hub_scope_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cameras'
                      AND COLUMN_NAME = 'monitor_hub_scope'
                    """
                )
                r = cur.fetchone()
                n = int(r["n"] if isinstance(r, dict) else r[0]) if r else 0
                if n < 1:
                    cur.execute(
                        """
                        ALTER TABLE cameras
                        ADD COLUMN monitor_hub_scope VARCHAR(16) NOT NULL DEFAULT 'local'
                        """
                    )
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_cam_hub_scope_done.add(key)


def _migrate_mysql_cameras_probe(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"probe:{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_probe_migration_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn:
            with conn.cursor() as cur:
                for col, ddl in (
                    ("offline_incidents", "INT UNSIGNED NOT NULL DEFAULT 0"),
                    ("last_rtsp_probe_ok", "TINYINT(1) NULL"),
                ):
                    cur.execute(
                        """
                        SELECT COUNT(*) AS n FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cameras' AND COLUMN_NAME = %s
                        """,
                        (col,),
                    )
                    r = cur.fetchone()
                    n = int(r["n"] if isinstance(r, dict) else r[0]) if r else 0
                    if n < 1:
                        cur.execute(f"ALTER TABLE cameras ADD COLUMN {col} {ddl}")
            conn.commit()
    except pymysql.Error:
        pass
    _mysql_probe_migration_done.add(key)


def _migrate_mysql_cameras_extra(settings: DatabaseSettings) -> None:
    if settings.backend != "mysql" or settings.mysql is None:
        return
    key = f"{settings.mysql.host}:{settings.mysql.port}:{settings.mysql.database}"
    if key in _mysql_extras_migration_done:
        return
    try:
        with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS ct FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'cameras' AND COLUMN_NAME = 'extras_json'
                """
            )
            row = cur.fetchone()
            cnt = int(row["ct"] if isinstance(row, dict) else row[0])
            if cnt == 0:
                cur.execute("ALTER TABLE cameras ADD COLUMN extras_json JSON NULL")
        _mysql_extras_migration_done.add(key)
    except pymysql.Error:
        raise


def _ensure_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), timeout=30.0)) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(_SQLITE_DDLS)
        _migrate_sqlite_cameras_extra(conn)
        _migrate_sqlite_cameras_probe(conn)
        _migrate_sqlite_cameras_hub_scope(conn)
        conn.commit()


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    _ensure_sqlite(path)
    return sqlite3.connect(str(path), timeout=30.0)


def list_cameras(settings: DatabaseSettings, hub_scope: str | None = None) -> list[CameraRow]:
    _migrate_mysql_cameras_extra(settings)
    _migrate_mysql_cameras_probe(settings)
    _migrate_mysql_cameras_hub_scope(settings)
    sql_base = """
        SELECT
            id,
            name,
            manufacturer,
            model,
            ip_address,
            http_port,
            rtsp_url,
            onvif_endpoint,
            is_enabled,
            last_seen_at,
            extras_json,
            COALESCE(offline_incidents, 0) AS offline_incidents,
            last_rtsp_probe_ok,
            monitor_hub_scope
        FROM cameras
    """
    params: tuple[Any, ...] = ()
    if hub_scope is not None and str(hub_scope).strip():
        sql = sql_base + " WHERE monitor_hub_scope = ? ORDER BY name"
        params = (_normalize_hub_scope_cam(hub_scope),)
    else:
        sql = sql_base + " ORDER BY name"
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


def _truncate(s: str, max_len: int) -> str:
    t = s.strip()
    if len(t) > max_len:
        return t[:max_len]
    return t


def validate_ip(s: str) -> str:
    t = s.strip()
    if not t:
        msg = "indique o endereço IP (IPv4 ou IPv6)"
        raise ValueError(msg)
    try:
        ipaddress.ip_address(t)
    except ValueError as e:
        msg = f"endereço IP inválido: {t!r}"
        raise ValueError(msg) from e
    return t


def compose_rtsp_url(
    ip_address: str,
    *,
    rtsp_url: str | None = None,
    rtsp_tcp_port: int | None = None,
    rtsp_path: str | None = None,
    rtsp_username: str | None = None,
    rtsp_password: str | None = None,
) -> str | None:
    """Monta rtsp://... a partir de IP + porta + caminho (+ credenciais). Ignora se rtsp_url já vier completo."""
    from urllib.parse import quote

    full = None if not rtsp_url or not str(rtsp_url).strip() else str(rtsp_url).strip()
    if full:
        return _truncate(full, 512)
    has_parts = (
        rtsp_tcp_port is not None
        or (rtsp_path and str(rtsp_path).strip())
        or (rtsp_username and str(rtsp_username).strip())
        or (rtsp_password and str(rtsp_password).strip())
    )
    if not has_parts:
        return None
    port = 554 if rtsp_tcp_port is None else int(rtsp_tcp_port)
    if not (1 <= port <= 65535):
        port = 554
    path = (rtsp_path or "").strip() or "/stream1"
    if not path.startswith("/"):
        path = "/" + path
    user = (rtsp_username or "").strip()
    pw = (rtsp_password or "").strip()
    ip = validate_ip(ip_address)
    if user or pw:
        auth = f"{quote(user, safe='')}:{quote(pw, safe='')}@"
    else:
        auth = ""
    return _truncate(f"rtsp://{auth}{ip}:{port}{path}", 512)


def _extras_to_json(extra: dict[str, Any] | None) -> str | None:
    if not extra:
        return None
    trimmed = {k: v for k, v in extra.items() if v is not None}
    if not trimmed:
        return None
    return _truncate(json.dumps(trimmed, ensure_ascii=False), 16384)


def insert_camera(
    settings: DatabaseSettings,
    *,
    name: str,
    ip_address: str,
    http_port: int | None,
    rtsp_url: str | None,
    onvif_endpoint: str | None,
    is_enabled: bool,
    manufacturer: str | None = None,
    model: str | None = None,
    extras: dict[str, Any] | None = None,
    monitor_hub_scope: str | None = None,
) -> str:
    _migrate_mysql_cameras_extra(settings)
    _migrate_mysql_cameras_probe(settings)
    _migrate_mysql_cameras_hub_scope(settings)
    ip = validate_ip(ip_address)
    n = _truncate(name, 128)
    mhs = _normalize_hub_scope_cam(monitor_hub_scope)
    rt = None if not rtsp_url or not (t := str(rtsp_url).strip()) else _truncate(t, 512)
    onv = None if not onvif_endpoint or not (u := str(onvif_endpoint).strip()) else _truncate(u, 512)
    mf = (
        None if not manufacturer or not str(manufacturer).strip() else _truncate(str(manufacturer).strip(), 64)
    )
    mo = None if not model or not str(model).strip() else _truncate(str(model).strip(), 64)
    ex_js = _extras_to_json(extras)
    new_id = uuid.uuid4()
    bin_id = uuid_to_dotnet_bytes(new_id)
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        created = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        sql = """
            INSERT INTO cameras
                (
                    id,
                    name,
                    manufacturer,
                    model,
                    ip_address,
                    http_port,
                    rtsp_url,
                    onvif_endpoint,
                    extras_json,
                    is_enabled,
                    last_seen_at,
                    offline_incidents,
                    last_rtsp_probe_ok,
                    monitor_hub_scope,
                    created_at
                )
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?)
        """
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.execute(
                sql,
                (
                    bin_id,
                    n,
                    mf,
                    mo,
                    _truncate(ip, 45),
                    http_port,
                    rt,
                    onv,
                    ex_js,
                    1 if is_enabled else 0,
                    mhs,
                    created,
                ),
            )
            conn.commit()
        return str(new_id)

    assert settings.mysql is not None
    sql_mysql = """
        INSERT INTO cameras
            (
                id,
                name,
                manufacturer,
                model,
                ip_address,
                http_port,
                rtsp_url,
                onvif_endpoint,
                extras_json,
                is_enabled,
                last_seen_at,
                offline_incidents,
                last_rtsp_probe_ok,
                monitor_hub_scope,
                created_at
            )
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, 0, NULL, %s, UTC_TIMESTAMP(3))
    """
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(
            sql_mysql,
            (
                bin_id,
                n,
                mf,
                mo,
                _truncate(ip, 45),
                http_port,
                rt,
                onv,
                ex_js,
                1 if is_enabled else 0,
                mhs,
            ),
        )
        conn.commit()
    return str(new_id)


def get_camera(settings: DatabaseSettings, id_str: str) -> CameraRow | None:
    from uuid import UUID

    _migrate_mysql_cameras_extra(settings)
    _migrate_mysql_cameras_probe(settings)
    _migrate_mysql_cameras_hub_scope(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    sql_sel = """
        SELECT
            id,
            name,
            manufacturer,
            model,
            ip_address,
            http_port,
            rtsp_url,
            onvif_endpoint,
            is_enabled,
            last_seen_at,
            extras_json,
            COALESCE(offline_incidents, 0) AS offline_incidents,
            last_rtsp_probe_ok,
            monitor_hub_scope
        FROM cameras
        WHERE id = ?
        LIMIT 1
    """
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql_sel, (bin_id,))
            r = cur.fetchone()
        if r is None:
            return None
        return _row_from_db(dict(r))

    assert settings.mysql is not None
    sql_mysql = """
        SELECT
            id,
            name,
            manufacturer,
            model,
            ip_address,
            http_port,
            rtsp_url,
            onvif_endpoint,
            is_enabled,
            last_seen_at,
            extras_json,
            COALESCE(offline_incidents, 0) AS offline_incidents,
            last_rtsp_probe_ok,
            monitor_hub_scope
        FROM cameras
        WHERE id = %s
        LIMIT 1
    """
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(sql_mysql, (bin_id,))
        r = cur.fetchone()
    if r is None:
        return None
    return _row_from_db(dict(r))


def update_camera(
    settings: DatabaseSettings,
    id_str: str,
    *,
    name: str,
    ip_address: str,
    http_port: int | None,
    rtsp_url: str | None,
    onvif_endpoint: str | None,
    is_enabled: bool,
    manufacturer: str | None = None,
    model: str | None = None,
    extras: dict[str, Any] | None = None,
    monitor_hub_scope: str | None = None,
) -> bool:
    from uuid import UUID

    _migrate_mysql_cameras_extra(settings)
    _migrate_mysql_cameras_probe(settings)
    _migrate_mysql_cameras_hub_scope(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    ip = validate_ip(ip_address)
    n = _truncate(name, 128)
    rt = None if not rtsp_url or not (ts := str(rtsp_url).strip()) else _truncate(ts, 512)
    onv = None if not onvif_endpoint or not (ov := str(onvif_endpoint).strip()) else _truncate(ov, 512)
    mf = (
        None if not manufacturer or not str(manufacturer).strip() else _truncate(str(manufacturer).strip(), 64)
    )
    mo = None if not model or not str(model).strip() else _truncate(str(model).strip(), 64)
    ex_js = _extras_to_json(extras)
    upd = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    mhs_new = _normalize_hub_scope_cam(monitor_hub_scope) if monitor_hub_scope is not None else None
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        sets_sql = [
            "name = ?",
            "manufacturer = ?",
            "model = ?",
            "ip_address = ?",
            "http_port = ?",
            "rtsp_url = ?",
            "onvif_endpoint = ?",
            "extras_json = ?",
            "is_enabled = ?",
            "updated_at = ?",
        ]
        params_cols: list[Any] = [
            n,
            mf,
            mo,
            _truncate(ip, 45),
            http_port,
            rt,
            onv,
            ex_js,
            1 if is_enabled else 0,
            upd,
        ]
        if mhs_new is not None:
            sets_sql.insert(-1, "monitor_hub_scope = ?")
            params_cols.insert(-1, mhs_new)
        sql_up = "UPDATE cameras SET " + ", ".join(sets_sql) + " WHERE id = ?"
        params_cols.append(bin_id)
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute(sql_up, tuple(params_cols))
            conn.commit()
            return cur.rowcount == 1

    assert settings.mysql is not None
    sets_m = [
        "name = %s",
        "manufacturer = %s",
        "model = %s",
        "ip_address = %s",
        "http_port = %s",
        "rtsp_url = %s",
        "onvif_endpoint = %s",
        "extras_json = %s",
        "is_enabled = %s",
    ]
    params_m2: list[Any] = [
        n,
        mf,
        mo,
        _truncate(ip, 45),
        http_port,
        rt,
        onv,
        ex_js,
        1 if is_enabled else 0,
    ]
    if mhs_new is not None:
        sets_m.append("monitor_hub_scope = %s")
        params_m2.append(mhs_new)
    sets_m.append("updated_at = UTC_TIMESTAMP(3)")
    params_m2.append(bin_id)
    sql_mysql = "UPDATE cameras SET " + ", ".join(sets_m) + " WHERE id = %s"
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute(sql_mysql, tuple(params_m2))
        conn.commit()
        return cur.rowcount == 1


def delete_camera(settings: DatabaseSettings, id_str: str) -> bool:
    from uuid import UUID

    _migrate_mysql_cameras_extra(settings)
    u = UUID(id_str)
    bin_id = uuid_to_dotnet_bytes(u)
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            cur = conn.execute("DELETE FROM cameras WHERE id = ?", (bin_id,))
            conn.commit()
            return cur.rowcount == 1

    assert settings.mysql is not None
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM cameras WHERE id = %s", (bin_id,))
        conn.commit()
        return cur.rowcount == 1


def _is_plausible_stream_url(s: str) -> bool:
    t = s.strip()
    if len(t) < 8:
        return False
    low = t.lower()
    if low.startswith(("rtsp://", "rtsps://", "rtmp://", "http://", "https://")):
        return True
    return "://" in t


def probe_rtsp(url: str, timeout_s: float = 5.0) -> tuple[bool, str | None]:
    s = (url or "").strip()
    if not s:
        return False, "URL vazia"
    if not _is_plausible_stream_url(s):
        return False, "não parece URL de stream (rtsp://…); confira rtsp_url na base"
    import cv2  # import local — só quando necessário

    def inner() -> tuple[bool, str | None]:
        cap = cv2.VideoCapture(s, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            return False, "não abriu o stream (rede, credenciais ou codec)"
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, min(8000, int(timeout_s * 1000)))
        except (AttributeError, TypeError, ValueError):
            pass
        ok, _ = cap.read()
        cap.release()
        if not ok:
            return False, "não leu frame inicial"
        return True, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(inner)
        try:
            return fut.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return False, f"tempo excedido ({timeout_s:.0f}s) ao abrir o stream"


def iter_mjpeg_multipart_from_rtsp(
    rtsp_url: str,
    *,
    jpeg_quality: int = 72,
    max_fps: float = 10.0,
    max_width: int = 1024,
    max_fail_streak: int = 48,
) -> Iterator[bytes]:
    """Frames JPEG em multipart boundary `frame`, para `StreamingResponse` (navegador `<img src=…>`).

    Cada ligação HTTP abre um ``VideoCapture`` próprio (uma sessão RTSP por cliente).
    """

    import time

    s = (rtsp_url or "").strip()
    if not s or not _is_plausible_stream_url(s):
        return

    import cv2

    cap = cv2.VideoCapture(s, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        return

    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except (AttributeError, TypeError, ValueError):
        pass

    min_interval = 1.0 / max(max_fps, 0.5)
    last_emit = 0.0
    fail_streak = 0
    q = max(30, min(98, int(jpeg_quality)))
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                fail_streak += 1
                if fail_streak >= max_fail_streak:
                    break
                time.sleep(0.04)
                continue
            fail_streak = 0
            now = time.monotonic()
            elapsed = now - last_emit
            if elapsed < min_interval:
                continue
            last_emit = now
            h, w = frame.shape[:2]
            if max_width > 0 and w > max_width:
                nh = max(1, int(h * (max_width / w)))
                frame = cv2.resize(frame, (max_width, nh), interpolation=cv2.INTER_AREA)
            enc_ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if not enc_ok:
                continue
            chunk = jpg.tobytes()
            header = (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(chunk)).encode("ascii") + b"\r\n\r\n"
            )
            yield header + chunk + b"\r\n"
    finally:
        cap.release()


def record_rtsp_probe_result(settings: DatabaseSettings, id_str: str, *, is_up: bool) -> None:
    """Actualiza último teste RTSP; incrementa ``offline_incidents`` quando passa de OK → falha."""
    from uuid import UUID

    _migrate_mysql_cameras_extra(settings)
    _migrate_mysql_cameras_probe(settings)
    try:
        u = UUID(id_str)
    except ValueError:
        return
    bin_id = uuid_to_dotnet_bytes(u)
    row = get_camera(settings, id_str)
    if row is None:
        return
    prev = row.last_rtsp_probe_ok
    bump = 1 if prev is True and not is_up else 0
    new_oi = max(0, int(row.offline_incidents)) + bump
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    flag = 1 if is_up else 0
    if settings.backend == "sqlite":
        assert settings.sqlite_path is not None
        _ensure_sqlite(settings.sqlite_path)
        with closing(_connect_sqlite(settings.sqlite_path)) as conn:
            if is_up:
                conn.execute(
                    """
                    UPDATE cameras SET
                        last_rtsp_probe_ok = ?,
                        offline_incidents = ?,
                        last_seen_at = ?,
                        updated_at = ?
                    WHERE id  = ?
                    """,
                    (flag, new_oi, now_iso, now_iso, bin_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE cameras SET
                        last_rtsp_probe_ok = ?,
                        offline_incidents = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (flag, new_oi, now_iso, bin_id),
                )
            conn.commit()
        return

    assert settings.mysql is not None
    with closing(_connect_mysql(settings.mysql)) as conn, conn.cursor() as cur:
        if is_up:
            cur.execute(
                """
                UPDATE cameras SET
                    last_rtsp_probe_ok = %s,
                    offline_incidents = %s,
                    last_seen_at = UTC_TIMESTAMP(3),
                    updated_at = UTC_TIMESTAMP(3)
                WHERE id = %s
                """,
                (flag, new_oi, bin_id),
            )
        else:
            cur.execute(
                """
                UPDATE cameras SET
                    last_rtsp_probe_ok = %s,
                    offline_incidents = %s,
                    updated_at = UTC_TIMESTAMP(3)
                WHERE id = %s
                """,
                (flag, new_oi, bin_id),
            )
        conn.commit()


def db_ping_error(settings: DatabaseSettings) -> str | None:
    """Testa SQLite ou MySQL conforme ``DatabaseSettings``."""
    try:
        if settings.backend == "sqlite":
            assert settings.sqlite_path is not None
            path = settings.sqlite_path
            path.parent.mkdir(parents=True, exist_ok=True)
            _ensure_sqlite(path)
            with closing(sqlite3.connect(str(path), timeout=5.0)) as conn:
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


def mysql_ping_error(settings: DatabaseSettings) -> str | None:
    """Alias retrocompatível; preferir ``db_ping_error``."""
    return db_ping_error(settings)
