"""Câmeras: leitura/escrita MySQL (tabela `cameras`) e teste de stream RTSP (OpenCV)."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.camera_ids import dotnet_bytes_to_uuid, uuid_to_dotnet_bytes
from app.db_settings import MysqlSettings


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


def _row_from_mysql(r: dict[str, Any]) -> CameraRow:
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
    is_en = bool(en) if en is not None else True
    ls = r.get("last_seen_at")
    last_iso: str | None = None
    if isinstance(ls, datetime):
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        last_iso = ls.astimezone(timezone.utc).isoformat()
    elif isinstance(ls, date):
        last_iso = datetime.combine(ls, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    return CameraRow(
        id=str(uid),
        name=name,
        ip_address=ip,
        http_port=port,
        rtsp_url=rtsp,
        onvif_endpoint=onvif,
        is_enabled=is_en,
        last_seen_utc=last_iso,
    )


def _connect(settings: MysqlSettings) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


def list_cameras(settings: MysqlSettings) -> list[CameraRow]:
    sql = """
        SELECT
            id, name, ip_address, http_port, rtsp_url, onvif_endpoint, is_enabled, last_seen_at
        FROM cameras
        ORDER BY name
    """
    with closing(_connect(settings)) as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    return [_row_from_mysql(dict(r)) for r in rows]


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


def insert_camera(
    settings: MysqlSettings,
    *,
    name: str,
    ip_address: str,
    http_port: int | None,
    rtsp_url: str | None,
    onvif_endpoint: str | None,
    is_enabled: bool,
) -> str:
    ip = validate_ip(ip_address)
    n = _truncate(name, 128)
    rt = None if not rtsp_url or not (t := str(rtsp_url).strip()) else _truncate(t, 512)
    onv = None if not onvif_endpoint or not (u := str(onvif_endpoint).strip()) else _truncate(u, 512)
    new_id = uuid.uuid4()
    bin_id = uuid_to_dotnet_bytes(new_id)
    sql = """
        INSERT INTO cameras
            (id, name, ip_address, http_port, rtsp_url, onvif_endpoint, is_enabled, last_seen_at, created_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, NULL, UTC_TIMESTAMP(3))
    """
    with closing(_connect(settings)) as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            (
                bin_id,
                n,
                _truncate(ip, 45),
                http_port,
                rt,
                onv,
                1 if is_enabled else 0,
            ),
        )
    return str(new_id)


def get_camera(settings: MysqlSettings, id_str: str) -> CameraRow | None:
    from uuid import UUID

    u = UUID(id_str)
    sql = """
        SELECT
            id, name, ip_address, http_port, rtsp_url, onvif_endpoint, is_enabled, last_seen_at
        FROM cameras
        WHERE id = %s
        LIMIT 1
    """
    bin_id = uuid_to_dotnet_bytes(u)
    with closing(_connect(settings)) as conn, conn.cursor() as cur:
        cur.execute(sql, (bin_id,))
        r = cur.fetchone()
    if r is None:
        return None
    return _row_from_mysql(dict(r))


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


def mysql_ping_error(settings: MysqlSettings) -> str | None:
    try:
        with closing(_connect(settings)) as conn:
            conn.ping()
    except pymysql.Error as e:
        return str(e)
    return None
