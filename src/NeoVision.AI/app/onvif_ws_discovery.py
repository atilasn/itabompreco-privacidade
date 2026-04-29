"""WS-Discovery (ONVIF), UDP 3702 — alinhado ao NeoVision.Desktop OnvifWsDiscovery."""

from __future__ import annotations

import re
import socket
import struct
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse


def _build_probe(include_network_video: bool) -> bytes:
    mid = f"urn:uuid:{uuid.uuid4()}"
    types_block = (
        '<d:Types xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        "dn:NetworkVideoTransmitter</d:Types>"
        if include_network_video
        else ""
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <s:Header>
    <a:MessageID>{mid}</a:MessageID>
    <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
    <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>
  </s:Header>
  <s:Body>
    <d:Probe>
      {types_block}
    </d:Probe>
  </s:Body>
</s:Envelope>"""
    return xml.encode("utf-8")


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _host_from_url(u: str) -> str | None:
    p = (u or "").strip()
    if not p:
        return None
    try:
        if "://" not in p:
            p = "http://" + p
        h = urlparse(p).hostname
        return h if h else None
    except (OSError, ValueError, TypeError):
        return None


def _parse_probe_response(
    xml_raw: str,
    seen: set[str],
    out: list[dict[str, Any]],
    remote_ip: str | None,
) -> None:
    if len(xml_raw) < 20 or "XAddrs" not in xml_raw:
        return
    scopes_val: str | None = None
    xaddrs_list: list[str] = []
    try:
        root = ET.fromstring(xml_raw)
        for el in root.iter():
            if _local_tag(el.tag) == "Scopes" and el.text:
                scopes_val = el.text.strip()
        for el in root.iter():
            if _local_tag(el.tag) != "XAddrs" or not el.text:
                continue
            raw = el.text.strip()
            for addr in raw.split():
                t = addr.strip()
                if t:
                    xaddrs_list.append(t)
    except ET.ParseError:
        mm = re.search(r"<[^>]*XAddrs[^>]*>\s*([^<]+)\s*</", xml_raw, re.I | re.DOTALL)
        if mm:
            for addr in mm.group(1).split():
                t = addr.strip()
                if t:
                    xaddrs_list.append(t)

    if not xaddrs_list:
        return
    primary = xaddrs_list[0]
    key = primary.lower()
    if key in seen:
        return
    seen.add(key)
    ip_hint = _host_from_url(primary) or remote_ip
    out.append(
        {
            "onvif_endpoint": primary,
            "xaddrs": xaddrs_list,
            "scopes": scopes_val,
            "remote_ip": remote_ip,
            "ip_hint": ip_hint,
        }
    )


def probe_network(listen_seconds: float = 4.0) -> list[dict[str, Any]]:
    """Envia Probe WS-Discovery e recolhe respostas até ao prazo. Firewall UDP 3702 na mesma LAN."""
    multicast = ("239.255.255.250", 3702)
    deadline = time.monotonic() + max(1.0, min(15.0, float(listen_seconds)))
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.bind(("", 0))
        udp.settimeout(0.4)
        try:
            udp.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 2)
            )
        except OSError:
            pass
        udp.sendto(_build_probe(True), multicast)
        udp.sendto(_build_probe(False), multicast)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            try:
                data, addr = udp.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            remote_ip = addr[0] if addr else None
            try:
                xml_raw = data.decode("utf-8", errors="ignore")
            except (UnicodeDecodeError, LookupError):
                continue
            _parse_probe_response(xml_raw, seen, out, remote_ip)
        return out
    finally:
        try:
            udp.close()
        except OSError:
            pass
