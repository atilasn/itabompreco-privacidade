"""Lista perfis Media ONVIF e URIs RTSP (GetProfiles + GetStreamUri)."""

from __future__ import annotations

import ipaddress
from typing import Any


def normalize_onvif_host(host: str) -> str:
    t = host.strip()
    if not t:
        msg = "indique ip_address ou hostname"
        raise ValueError(msg)
    try:
        ipaddress.ip_address(t)
    except ValueError:
        # hostname simples
        if len(t) > 253:
            msg = "hostname demasiado longo"
            raise ValueError(msg)
    return t


def list_media_stream_uris(
    host: str,
    port: int,
    username: str,
    password: str,
) -> list[dict[str, Any]]:
    """Devolve lista de perfis com token, nome legível e rtsp_uri (vazio se falhar esse perfil)."""
    try:
        from onvif import ONVIFCamera
    except ImportError:
        msg = (
            "Dependência ONVIF em falta. Instale: pip install onvif-zeep"
        )
        raise RuntimeError(msg) from None

    h = normalize_onvif_host(host)
    p = int(port)
    if not (1 <= p <= 65535):
        raise ValueError("http_port deve estar entre 1 e 65535")

    u = username or ""
    pw = password or ""

    cam = ONVIFCamera(h, p, u, pw)
    media = cam.create_media_service()
    profs = media.GetProfiles()

    out: list[dict[str, Any]] = []
    stream_setup = {
        "Stream": "RTP-Unicast",
        "Transport": {"Protocol": "RTSP"},
    }
    for pr in profs:
        token = getattr(pr, "token", None) or ""
        name = getattr(pr, "Name", None) or getattr(pr, "name", None) or token
        rtsp_uri = ""
        last_err = ""
        try:
            su = media.GetStreamUri(
                {"StreamSetup": stream_setup, "ProfileToken": token},
            )
            if su is not None and getattr(su, "Uri", None):
                rtsp_uri = str(su.Uri).strip()
        except Exception as e:
            last_err = str(e)[:200]
        out.append(
            {
                "token": token,
                "name": str(name)[:256],
                "rtsp_uri": rtsp_uri,
                "warning": last_err or None,
            },
        )

    return out
