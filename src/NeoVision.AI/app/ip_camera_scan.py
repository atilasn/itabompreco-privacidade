"""Varrimento TCP em portas comuns de CCTV (câmaras IP sem anúncio ONVIF na mesma LAN).

Usa apenas a biblioteca standard: tenta redes /24 à volta dos IPv4 locais não loopback,
em paralelo, com timeouts curtos. Não garante apenas câmeras — qualquer hospedeiro com as
mesmas portas abertas pode aparecer como candidato."""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any

SCAN_TCP_PORTS: tuple[int, ...] = (
    554,
    8554,
    37777,
    80,
    8080,
    8000,
    443,
    8443,
    888,
)


def _local_primary_ipv4() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("224.0.0.251", 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if isinstance(ip, str) and ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return None


def _extra_local_ipv4s(max_addrs: int) -> list[str]:
    out: list[str] = []
    try:
        host = socket.gethostname()
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return out
    for inf in infos:
        ip = inf[4][0]
        if ip and isinstance(ip, str) and not ip.startswith("127."):
            if ip not in out:
                out.append(ip)
        if len(out) >= max_addrs:
            break
    return out


def _hosts_slash24(anchor_ipv4: str) -> list[str]:
    try:
        net = ipaddress.IPv4Network(f"{anchor_ipv4.strip()}/24", strict=False)
    except ValueError:
        return []
    return [str(ip) for ip in net.hosts()]


def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _merge_unique_hosts(network_anchors: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for a in network_anchors:
        for h in _hosts_slash24(a):
            if h not in seen:
                seen.add(h)
                merged.append(h)
    return merged


def probe_tcp_camera_hosts(
    *,
    ports: tuple[int, ...] = SCAN_TCP_PORTS,
    connect_timeout: float = 0.2,
    max_workers: int = 96,
) -> list[dict[str, Any]]:
    """Percorre /24 sobre cada rede local detectável; devolve candidatos com portas abertas.

    Mais lento que ONVIF: pode ultrapassar 10–20 s numa VLAN completa; limitar concorrência
    evita bloqueios em máquinas com poucas ligações.
    """

    anchors: list[str] = []
    prim = _local_primary_ipv4()
    if prim:
        anchors.append(prim)
    for x in _extra_local_ipv4s(max_addrs=4):
        if x not in anchors:
            anchors.append(x)

    hosts = _merge_unique_hosts(anchors)
    if not hosts:
        return []

    tasks = [(host, pt) for host in hosts for pt in ports]

    def check_pair(args: tuple[str, int]) -> tuple[str, int] | None:
        h, pt = args
        if _tcp_open(h, pt, connect_timeout):
            return (h, pt)
        return None

    hits: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        # map mantém paralelização com limite pelo pool
        for r in ex.map(check_pair, tasks, chunksize=32):
            if r:
                hits.append(r)

    by_ip: dict[str, list[int]] = {}
    for hip, pt in hits:
        by_ip.setdefault(hip, []).append(pt)

    RTSP_PRIO = {554: 101, 8554: 100, 37777: 99}

    keyed: list[tuple[tuple[int, tuple[int, int, int, int]], dict[str, Any]]] = []
    for ip_s, plist in by_ip.items():
        plist_u = sorted(set(plist))
        prio_pts = sum(RTSP_PRIO.get(p, 0) for p in plist_u)
        scopes = "Varrimento IP (TCP): portas " + ", ".join(str(x) for x in plist_u)
        row = {
            "onvif_endpoint": None,
            "xaddrs": [],
            "scopes": scopes,
            "remote_ip": ip_s,
            "ip_hint": ip_s,
            "discovery_source": "ip",
            "open_ports": plist_u,
        }
        ipv4_tuple = tuple(int(x) for x in ip_s.split("."))
        # Menor `sort_key`: mais portas relacionadas RTSP aparecem primeiro.
        keyed.append(((-prio_pts, ipv4_tuple), row))

    keyed.sort(key=lambda kv: kv[0])
    return [rel for _k, rel in keyed]
