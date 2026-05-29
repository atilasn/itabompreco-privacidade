# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: dist/NeoVision-Rede/NeoVision-Rede.exe — mesma stack que NeoVision-Sistema,
# mas abre só a página de monitorização de rede (ver desktop_rede.py).
# Ou: powershell -ExecutionPolicy Bypass -File repo\build\publish-rede-desktop-python.ps1

import importlib.util
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

d_cv2, b_cv2, h_cv2 = collect_all("cv2", include_py_files=True)

try:
    d_wv, b_wv, h_wv = collect_all("webview", include_py_files=True)
except Exception:
    d_wv, b_wv, h_wv = [], [], []

_extra_wsdl: list[tuple[str, str]] = []
try:
    _spec = importlib.util.find_spec("onvif")
    if _spec and _spec.origin:
        _wsdl_dir = Path(_spec.origin).resolve().parent.parent / "wsdl"
        if _wsdl_dir.is_dir():
            _extra_wsdl = [(str(_wsdl_dir), "wsdl")]
except Exception:
    pass

try:
    d_zp, b_zp, h_zp = collect_all("zeep", include_py_files=True)
except Exception:
    d_zp, b_zp, h_zp = [], [], []

hidden = (
    h_cv2
    + h_wv
    + list(collect_submodules("app"))
    + list(collect_submodules("webview"))
    + [
        "webview.platforms.edgechromium",
        "uvicorn",
        "pymysql",
        "pymysql.cursors",
        "pydantic",
        "pydantic_core",
        "httptools",
        "websockets",
        "anyio",
        "h11",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.loops.asyncio",
        "uvicorn.logging",
        "watchfiles",
        "multipart",
        "python_multipart",
        "starlette",
        "webview",
        "onvif",
        "app.onvif_streams",
        "zeep",
    ]
    + list(h_zp)
)

a = Analysis(
    ["desktop_rede.py"],
    pathex=[],
    binaries=b_cv2 + b_wv + b_zp,
    datas=[("static", "static")] + d_cv2 + d_wv + d_zp + _extra_wsdl,
    hiddenimports=hidden + ["desktop_sistema"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeoVision-Rede",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NeoVision-Rede",
)
