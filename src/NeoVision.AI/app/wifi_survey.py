"""Levantamento de redes Wi‑Fi visíveis (Windows, `netsh`) — canal, sinal e MAC do AP (BSSID)."""

from __future__ import annotations

import platform
import re
import subprocess
from typing import Any

from app.wifi_oui import classify_wifi_bssid


def _run_netsh_bssid() -> str:
    if platform.system() != "Windows":
        raise OSError("Somente Windows.")
    cr = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        cr = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.run(
        ["netsh", "wlan", "show", "networks", "mode=Bssid"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        creationflags=cr,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(err or f"netsh saiu com código {proc.returncode}")
    return proc.stdout or ""


def _parse_netsh_bssid(text: str) -> list[dict[str, Any]]:
    """Interpreta saída de `netsh wlan show networks mode=Bssid` (EN/PT mistos)."""
    out: list[dict[str, Any]] = []
    ssid = ""
    cur: dict[str, Any] | None = None

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue

        mssid = re.match(r"SSID\s+\d+\s*:\s*(.*)$", line)
        if mssid:
            ssid = (mssid.group(1) or "").strip()
            cur = None
            continue

        mb = re.match(r"\s*BSSID\s+\d+\s*:\s*([0-9a-fA-F:]{17})\s*$", line)
        if mb:
            if cur:
                out.append(cur)
            cur = {
                "ssid": ssid,
                "bssid": mb.group(1).lower(),
                "signal_pct": None,
                "channel": None,
                "radio_type": None,
                "band": None,
                "authentication": None,
                "encryption": None,
            }
            continue

        if cur is None or ":" not in line:
            continue

        key_raw, _, val = line.partition(":")
        key = " ".join(key_raw.split()).lower()
        val = val.strip()

        if "signal" in key or "sinal" in key:
            m = re.search(r"(\d+)\s*%", val)
            if m:
                cur["signal_pct"] = int(m.group(1))
        elif "channel" in key or "canal" in key:
            m = re.search(r"\d+", val)
            if m:
                cur["channel"] = int(m.group(0))
        elif "radio" in key:
            cur["radio_type"] = val or None
        elif "band" in key or "banda" in key:
            cur["band"] = val or None
        elif "authentication" in key or "autenticação" in key or "autentic" in key:
            cur["authentication"] = val or None
        elif "encryption" in key or "encript" in key:
            cur["encryption"] = val or None

    if cur:
        out.append(cur)
    for row in out:
        vend, ap_hint = classify_wifi_bssid(str(row.get("bssid") or ""))
        row["vendor"] = vend
        row["ap_hint"] = ap_hint
    return out


def survey_visible_networks() -> dict[str, Any]:
    """
    Lista BSSIDs visíveis (Windows / netsh): canal, intensidade, MAC; fabricante estimado por OUI (ex. UniFi).
    Requer adaptador Wi‑Fi no Windows; sem ele, `netsh` devolve erro.
    """
    if platform.system() != "Windows":
        return {
            "platform_supported": False,
            "error": None,
            "note": "Levantamento Wi‑Fi está disponível apenas no Windows (netsh wlan).",
            "networks": [],
        }

    try:
        raw = _run_netsh_bssid()
        nets = _parse_netsh_bssid(raw)
        if not nets and "there is no wireless" in raw.lower():
            return {
                "platform_supported": True,
                "error": "Sem interface Wi‑Fi ativa ou sem redes no alcance.",
                "note": raw.strip()[:500] if raw.strip() else None,
                "networks": [],
            }
        return {
            "platform_supported": True,
            "error": None,
            "note": "Redes à vista: canal, intensidade, MAC (BSSID) e fabricante estimado (OUI).",
            "networks": nets,
        }
    except subprocess.TimeoutExpired:
        return {
            "platform_supported": True,
            "error": "Tempo esgotado ao executar netsh.",
            "note": None,
            "networks": [],
        }
    except (OSError, RuntimeError) as e:
        return {
            "platform_supported": True,
            "error": str(e),
            "note": None,
            "networks": [],
        }
