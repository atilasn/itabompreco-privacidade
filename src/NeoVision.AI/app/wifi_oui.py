"""Prefixos OUI (IEEE) para identificar fabricante do BSSID — foco em Ubiquiti / UniFi."""

from __future__ import annotations

# Conjunto representativo Ubiquiti Inc. / UniFi (Wi‑Fi). Identificação por MAC não é 100% exata.
_UBIQUITI_OUI: frozenset[str] = frozenset(
    {
        "00:15:6d",
        "04:18:d6",
        "18:e8:29",
        "24:a4:3c",
        "44:d9:e7",
        "60:22:32",
        "68:72:51",
        "74:83:c2",
        "78:8a:20",
        "80:2a:a8",
        "ac:8b:a9",
        "b4:fb:e4",
        "dc:9f:db",
        "e0:63:da",
        "f0:9f:c2",
        "f4:92:bf",
    }
)


def oui_from_bssid(bssid: str) -> str | None:
    t = (bssid or "").strip().lower().replace("-", ":")
    parts = [p for p in t.split(":") if p]
    if len(parts) < 3:
        return None
    return ":".join(parts[:3])


def classify_wifi_bssid(bssid: str) -> tuple[str | None, str | None]:
    """
    Devolve (fabricante_curto, dica_ap).
    Para Ubiquiti: dica indica provável equipamento UniFi / AP Ubiquiti.
    """
    oui = oui_from_bssid(bssid)
    if not oui:
        return None, None
    if oui in _UBIQUITI_OUI:
        return "Ubiquiti", "Provável AP UniFi / Ubiquiti (OUI do MAC)"
    return None, None
