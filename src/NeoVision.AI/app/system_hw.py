"""Relógio do servidor e discos físicos (Windows: Get-PhysicalDisk, resumo de saúde)."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from typing import Any


def server_clock() -> dict[str, str]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    utc_iso = now.isoformat().replace("+00:00", "Z")
    try:
        local = datetime.now().astimezone()
        local_iso = local.replace(microsecond=0).isoformat()
        tz = str(local.tzname() or "") or str(local.tzinfo or "")
    except (OSError, TypeError, ValueError):
        local_iso = utc_iso
        tz = "UTC"
    return {
        "utc_iso": utc_iso,
        "local_iso": local_iso,
        "timezone_name": tz,
    }


def _powershell_json(command: str, timeout: float = 45.0) -> tuple[Any, str | None]:
    if platform.system().lower() != "windows":
        return None, "not_windows"
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return None, err or out or f"exit_{proc.returncode}"
    if not out:
        return None, "empty_output"
    try:
        return json.loads(out), None
    except json.JSONDecodeError as e:
        return None, f"json:{e}"


def list_physical_disks() -> tuple[list[dict[str, Any]], str | None]:
    """Enumera discos físicos (saúde segundo o Windows / storage)."""
    ps = r"""
$disks = @(Get-PhysicalDisk -ErrorAction Stop)
$rows = foreach ($d in $disks) {
  [PSCustomObject]@{
    device_id = [int]$d.DeviceId
    friendly_name = [string]$d.FriendlyName
    media_type = $d.MediaType.ToString()
    size_bytes = [int64]$d.Size
    health_status = $d.HealthStatus.ToString()
    operational_status = $d.OperationalStatus.ToString()
    bus_type = $d.BusType.ToString()
    serial_number = $d.SerialNumber
    unique_id = $d.UniqueId
  }
}
$rows | ConvertTo-Json -Compress -Depth 5
"""
    data, err = _powershell_json(ps.strip(), timeout=35.0)
    if err == "not_windows":
        return [], "not_windows"
    if err:
        return [], err
    if data is None:
        return [], "no_data"
    if isinstance(data, dict):
        return [data], None
    if isinstance(data, list):
        return data, None
    return [], "unexpected_shape"


def physical_disk_detail(device_id: int) -> tuple[dict[str, Any] | None, str | None]:
    """Detalhe ao clicar num disco: disco + contadores de fiabilidade quando existirem."""
    if device_id < 0 or device_id > 1024:
        return None, "invalid_device_id"
    did = int(device_id)
    # -DeviceId não existe no cmdlet; comparar como int (evita falhas de tipo no Where-Object).
    ps_disk = f"""
$did = [int]{did}
$disk = @(Get-PhysicalDisk -ErrorAction Stop | Where-Object {{ [int]$_.DeviceId -eq $did }})
if ($disk.Count -lt 1) {{ throw "disk_missing" }}
$disk[0] | ConvertTo-Json -Depth 8 -Compress
"""
    raw, err = _powershell_json(ps_disk.strip(), timeout=25.0)
    if err:
        return None, err
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if not isinstance(raw, dict):
        return None, "not_object"

    ps_rel = f"""
$did = [int]{did}
$disk = @(Get-PhysicalDisk -ErrorAction Stop | Where-Object {{ [int]$_.DeviceId -eq $did }})
if ($disk.Count -lt 1) {{ Write-Output 'null' }} else {{
  $r = Get-StorageReliabilityCounter -PhysicalDisk $disk[0] -ErrorAction SilentlyContinue
  if ($null -eq $r) {{ Write-Output 'null' }} else {{
    $r | ConvertTo-Json -Depth 6 -Compress
  }}
}}
"""
    rel_any, _rel_err = _powershell_json(ps_rel.strip(), timeout=20.0)
    reliability: dict[str, Any] | None = None
    if isinstance(rel_any, dict):
        reliability = rel_any
    elif isinstance(rel_any, list) and rel_any:
        reliability = rel_any[0] if isinstance(rel_any[0], dict) else None
    else:
        reliability = None

    return {"disk": raw, "reliability": reliability}, None
