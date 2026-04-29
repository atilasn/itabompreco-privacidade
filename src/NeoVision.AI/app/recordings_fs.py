"""Listagem segura de ficheiros na pasta `recordings` (vídeo gravados no servidor NeoVision)."""

from __future__ import annotations

import pathlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone


VIDEO_SUFFIXES = frozenset(
    {
        ".mp4",
        ".mkv",
        ".webm",
        ".avi",
        ".mov",
        ".mpeg",
        ".mpg",
        ".m4v",
    },
)


def _mtime_utc(p: pathlib.Path) -> datetime:
    st = p.stat()
    sec = float(st.st_mtime)
    return datetime.fromtimestamp(sec, tz=timezone.utc)


@dataclass(frozen=True)
class RecordingFileScan:
    relative_path_posix: str
    modified_utc: datetime
    size_bytes: int


def safe_file_under(root: pathlib.Path, rel_posix: str) -> pathlib.Path | None:
    """Resolve `rel_posix` (sem ..) para um ficheiro dentro de `root`."""
    root = root.resolve()
    rel = (rel_posix or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/"):
        return None
    pure = pathlib.PurePosixPath(rel)
    if ".." in pure.parts:
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def recordings_match_hint(rel_lower: str, camera_id: uuid.UUID, name: str, ip: str) -> bool:
    """Heurística: pastas ou nomes de ficheiros que sugiram uma câmara registada."""
    uid_compact = camera_id.hex
    uid_short = str(camera_id).replace("-", "")[:12]
    if uid_compact[:8] in rel_lower.replace("-", "") or uid_short in rel_lower:
        return True
    ip_dots = ip.strip().replace(" ", "")
    if len(ip_dots) >= 7 and ip_dots in rel_lower:
        return True
    ip_plain = ip_dots.replace(".", "")
    if len(ip_plain) >= 8:
        cand = "".join(rel_lower.split("."))
        if ip_plain in cand:
            return True
    slug = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if len(slug) >= 3 and slug in rel_lower:
        return True
    loose = "".join((name or "").lower().split())
    if len(loose) >= 4 and loose in rel_lower:
        return True
    return False


def list_recordings_in_range(
    root: pathlib.Path,
    *,
    start_utc: datetime,
    end_utc: datetime,
    match_camera_filter: Callable[[RecordingFileScan], bool] | None = None,
) -> list[RecordingFileScan]:
    """Enumera vídeos com data de modificação no intervalo (UTC). Pasta inexistente → lista vazia."""
    root = root.resolve()
    out: list[RecordingFileScan] = []
    if not root.is_dir():
        return out

    try:
        for p in root.rglob("*"):
            try:
                if not p.is_file():
                    continue
                if p.suffix.lower() not in VIDEO_SUFFIXES:
                    continue
                parts = pathlib.PurePosixPath(p.as_posix()).parts
                if any(part.startswith(".") for part in parts):
                    continue
                mod = _mtime_utc(p)
                if mod < start_utc or mod > end_utc:
                    continue
                try:
                    rel_posix = p.relative_to(root).as_posix()
                except ValueError:
                    continue
                item = RecordingFileScan(
                    relative_path_posix=rel_posix,
                    modified_utc=mod,
                    size_bytes=int(p.stat().st_size),
                )
                if match_camera_filter is not None and not match_camera_filter(item):
                    continue
                out.append(item)
            except OSError:
                continue
    except OSError:
        return out

    out.sort(key=lambda x: x.modified_utc, reverse=True)
    return out
