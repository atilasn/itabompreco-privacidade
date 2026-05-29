"""Gravação contínua de streams RTSP das câmaras registadas (alternativa DVR/NVR).

Escreve segmentos de vídeo em ``storage.recordings_dir()/cam_<uuid_hex>/`` para associação
automática pelo painel de Gravações (heurística em ``recordings_fs.recordings_match_hint``).

Requisito operacional: **ffmpeg** no PATH ou ``NEOVISION_FFMPEG`` com caminho ao executável.
Desativar totalmente: ``NEOVISION_RECORDING_DISABLED=1``.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass

from app import storage

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db_settings import DatabaseSettings

log = logging.getLogger(__name__)

_WARNED_NO_FFMPEG = False

_DEFAULT_SEGMENT_SECONDS = int(os.environ.get("NEOVISION_RECORD_SEGMENT_SEC", "").strip() or "900")


def _recording_disabled() -> bool:
    v = os.environ.get("NEOVISION_RECORDING_DISABLED", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _ffmpeg_exe() -> str | None:
    explicit = os.environ.get("NEOVISION_FFMPEG", "").strip()
    if explicit:
        p = pathlib.Path(explicit)
        return str(p.expanduser()) if p.is_file() else None
    return shutil.which("ffmpeg")


def _camera_folder_name(cam_id: str) -> str:
    uid = uuid.UUID(cam_id.strip())
    return f"cam_{uid.hex}"


def _safe_rtsp_fragment(url: str) -> str:
    """Nome de ficheiro curto apenas para debugging (sem palavras-passe na totalidade)."""
    t = url.strip().split("@", maxsplit=1)[-1]
    t = re.sub(r"\s+", "_", t)[:64]
    return t or "rtsp"


@dataclass
class RecorderProcessInfo:
    popen: subprocess.Popen[bytes]
    rtsp_url: str


class IpCameraRecorder:
    """Um processo ffmpeg por câmara permitida."""

    def __init__(self, *, segment_seconds: int | None = None) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, RecorderProcessInfo] = {}
        self._segment_seconds = max(120, segment_seconds if segment_seconds is not None else _DEFAULT_SEGMENT_SECONDS)

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._by_id.keys())
        for cid in ids:
            self._stop_locked(cid)

    def refresh(self, settings: DatabaseSettings) -> None:
        if _recording_disabled():
            self.stop_all()
            return

        exe = _ffmpeg_exe()
        global _WARNED_NO_FFMPEG  # noqa: PLW0603
        if exe is None:
            if not _WARNED_NO_FFMPEG:
                log.warning(
                    "Gravação RTSP ignorada: ffmpeg não encontrado. "
                    "Instale FFmpeg ou defina NEOVISION_FFMPEG (caminho completo).",
                )
                _WARNED_NO_FFMPEG = True
            self.stop_all()
            return

        from app.cameras import list_cameras

        wanted: dict[str, str] = {}
        for row in list_cameras(settings):
            if not row.is_enabled:
                continue
            url = (row.rtsp_url or "").strip()
            if not url:
                continue
            wanted[row.id] = url

        with self._lock:
            for cid in list(self._by_id.keys()):
                if cid not in wanted:
                    self._terminate_one(cid)
                elif self._by_id[cid].rtsp_url != wanted[cid]:
                    self._terminate_one(cid)

            for cid in list(self._by_id.keys()):
                inf = self._by_id[cid]
                if inf.popen.poll() is not None:
                    code = inf.popen.returncode
                    self._by_id.pop(cid, None)
                    log.warning("ffmpeg terminou durante gravação (câmara %s código=%s); será reaberto.", cid, code)

            for cid, url in wanted.items():
                if cid in self._by_id:
                    continue
                self._start_one_locked(exe, cid, url)

    def _stop_locked(self, cam_id: str) -> None:
        with self._lock:
            self._terminate_one(cam_id)

    def _terminate_one(self, cam_id: str) -> None:
        info = self._by_id.pop(cam_id, None)
        if info is None:
            return
        proc = info.popen
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=4)

    def _start_one_locked(self, ffmpeg: str, cam_id: str, rtsp_url: str) -> None:
        root = storage.recordings_dir()
        try:
            sub = root / _camera_folder_name(cam_id)
            sub.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.error("Não foi possível criar pasta de gravação para câmara %s: %s", cam_id, e)
            return

        out_pattern = str(sub / "seg_%03d.mkv")
        # Remux cópia direta quando possível; segmentos MKV são robustos entre cortes.
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-rtsp_transport",
            "tcp",
            "-i",
            rtsp_url,
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(self._segment_seconds),
            "-reset_timestamps",
            "1",
            "-break_non_keyframes",
            "1",
            out_pattern,
        ]
        hint = _safe_rtsp_fragment(rtsp_url)

        popen_kw: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
            popen_kw["creationflags"] = creationflags

        try:
            proc = subprocess.Popen(cmd, **popen_kw)
        except OSError as e:
            log.error("Falha ao iniciar ffmpeg para câmara %s (%s): %s", cam_id, hint, e)
            return

        self._by_id[cam_id] = RecorderProcessInfo(popen=proc, rtsp_url=rtsp_url)
        log.info("Gravação RTSP iniciada: câmara=%s pasta=%s", cam_id, sub.name)

        # Rever processos já mortos (URL inválida, rede, etc.).
        threading.Thread(target=self._observe_early_exit, args=(cam_id,), daemon=True).start()

    def _observe_early_exit(self, cam_id: str) -> None:
        time.sleep(2.5)
        with self._lock:
            info = self._by_id.get(cam_id)
        if info is None:
            return
        if info.popen.poll() is not None:
            log.warning(
                "ffmpeg terminou pouco depois do arranque (câmara %s código=%s). Verifique URL RTSP e rede.",
                cam_id,
                info.popen.returncode,
            )
            with self._lock:
                self._by_id.pop(cam_id, None)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            rows = []
            for cid, inf in sorted(self._by_id.items(), key=lambda x: x[0]):
                proc = inf.popen
                rows.append(
                    {
                        "camera_id": cid,
                        "recording": proc.poll() is None,
                        "pid": proc.pid,
                        "rtsp_digest": _safe_rtsp_fragment(inf.rtsp_url),
                        "segment_seconds": self._segment_seconds,
                    }
                )
        return {
            "recording_enabled_global": not _recording_disabled(),
            "ffmpeg_present": _ffmpeg_exe() is not None,
            "segment_seconds": self._segment_seconds,
            "cameras": rows,
        }


_recorder_singleton: IpCameraRecorder | None = None
_recorder_singleton_lock = threading.Lock()


def get_recorder() -> IpCameraRecorder:
    global _recorder_singleton
    with _recorder_singleton_lock:
        if _recorder_singleton is None:
            _recorder_singleton = IpCameraRecorder()
        return _recorder_singleton
