"""Varredura ICMP na LAN (estilo Advanced IP Scanner) — apenas IPv4, rede local."""

from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.ip_camera_scan import (
    _extra_local_ipv4s,
    _merge_unique_hosts,
    _local_primary_ipv4,
)


def _hosts_for_user_cidr(cidr: str, *, max_hosts: int) -> tuple[list[str], str]:
    raw = (cidr or "").strip()
    low = raw.lower()
    if not raw or low in ("auto", "local", "*"):
        anchors: list[str] = []
        p = _local_primary_ipv4()
        if p:
            anchors.append(p)
        for x in _extra_local_ipv4s(max_addrs=8):
            if x not in anchors:
                anchors.append(x)
        if not anchors:
            raise ValueError("Nenhum IPv4 local detectável (WLAN/Ethernet?).")
        hosts = _merge_unique_hosts(anchors)
        nets = sorted({_network_label(a) for a in anchors})
        label = ", ".join(nets)
        summary = "Redes automáticas · " + label
    else:
        try:
            net = ipaddress.ip_network(raw, strict=False)
        except ValueError as e:
            raise ValueError("CIDR inválido (ex.: 192.168.1.0/24).") from e
        if not isinstance(net, ipaddress.IPv4Network):
            raise ValueError("Somente IPv4.")
        if net.prefixlen < 20:
            raise ValueError("Rede grande demais para o painel (mínimo prefixo /20, ex.: 10.0.0.0/20).")
        hosts = [str(ip) for ip in net.hosts()]
        summary = str(net)

    if not hosts:
        raise ValueError("Nenhum endereço a varrer.")
    if len(hosts) > max_hosts:
        raise ValueError(f"Limite NeoVision: no máximo {max_hosts} endereços por varredura.")
    return hosts, summary


def _network_label(anchor_ipv4: str) -> str:
    try:
        net = ipaddress.IPv4Network(f"{anchor_ipv4.strip()}/24", strict=False)
        return str(net)
    except ValueError:
        return anchor_ipv4


def ping_icmp_ms(ip: str, timeout_ms: int) -> tuple[bool, float | None]:
    """Uma jogada ICMP; devolve (respondeu?, tempo_aprox_ms)."""
    t = (ip or "").strip()
    if not t:
        return False, None
    timeout_ms = max(250, min(10000, int(timeout_ms)))
    try:
        if platform.system() == "Windows":
            proc = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), t],
                capture_output=True,
                timeout=max(3.5, timeout_ms / 1000 + 3.5),
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
        return False, None

    lo = out.lower()
    ok = False
    if "ttl=" in lo:
        ok = True
    elif platform.system() != "Windows" and ("bytes from" in lo or "icmp_seq" in lo):
        ok = True
    elif ("resposta de" in lo or "reply from" in lo) and ("bytes=" in lo or "<1" in lo):
        ok = True

    if not ok:
        return False, None

    ms = _parse_ping_ms(out)
    return True, ms


def _parse_ping_ms(out: str) -> float | None:
    lo = out.replace("\xa0", " ").lower()
    m = re.search(r"(?:tempo|time)\s*=?\s*(\d+)\s*m?s\b", lo)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    if re.search(r"(?:tempo|time)\s*<\s*1\b", lo) or re.search(r"<1\s*m?s\b", lo):
        return 0.25
    return None


def _resolve_hostname_best_effort(ip: str) -> str | None:
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name if isinstance(name, str) and name.strip() else None
    except OSError:
        return None


def scan_lan_ping(
    *,
    cidr: str = "auto",
    timeout_ms: int = 650,
    resolve_hostname: bool = True,
    max_hosts: int = 1024,
    max_workers: int = 48,
) -> dict[str, Any]:
    hosts, summary = _hosts_for_user_cidr(cidr, max_hosts=max_hosts)
    t0 = time.perf_counter()
    hits: dict[str, tuple[bool, float | None]] = {}

    with ThreadPoolExecutor(max_workers=min(max_workers, 96)) as ex:
        fut_map = {
            ex.submit(ping_icmp_ms, hip, timeout_ms): hip for hip in hosts
        }
        for fu in as_completed(fut_map):
            ip = fut_map[fu]
            try:
                alive, ms = fu.result()
                hits[ip] = (alive, ms)
            except Exception:
                hits[ip] = (False, None)

    ordered_ips = sorted(hosts, key=lambda x: tuple(int(p) for p in x.split(".")))
    results: list[dict[str, Any]] = []
    alive_n = 0
    for ip in ordered_ips:
        alive, ms = hits.get(ip, (False, None))
        if alive:
            alive_n += 1
        hn: str | None = None
        if alive and resolve_hostname:
            hn = _resolve_hostname_best_effort(ip)
        results.append(
            {
                "ip": ip,
                "alive": alive,
                "latency_ms": ms if alive else None,
                "hostname": hn,
            }
        )

    return {
        "cidr_note": summary,
        "total_ips": len(hosts),
        "alive_count": alive_n,
        "results": results,
        "duration_sec": round(time.perf_counter() - t0, 3),
    }
