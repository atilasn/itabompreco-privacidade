# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: gera `dist/NeoVision-API/NeoVision-API.exe` (pasta, não ficheiro único).
# Executar:  cd este diretório  ;  pyinstaller -y NeoVision-API.spec

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_submodules

d_cv2, b_cv2, h_cv2 = collect_all("cv2", include_py_files=True)
hidden = h_cv2 + list(collect_submodules("app")) + [
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
]

a = Analysis(
    ["run_api.py"],
    pathex=[],
    binaries=b_cv2,
    datas=[("static", "static")] + d_cv2,
    hiddenimports=hidden,
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
    name="NeoVision-API",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="NeoVision-API",
)
