"""NeoVision AI — serviço HTTP/WebSocket (OpenAPI em /contracts no repositório)."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from starlette.responses import Response

import mimetypes
import pathlib


from app.paths import package_root
from fastapi import FastAPI, HTTPException, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, FileResponse
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Models (alinhados a contracts/openapi.yaml)
# ---------------------------------------------------------------------------


class _Examples:
    root = {
        "service": "NeoVision AI",
        "neovision_api_build": "root-json-v2-gravacoes-painel",
        "endpoints": {
            "painel": "/painel",
            "gravacoes": "/static/painel/gravacoes.html",
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health",
            "openapi": "/openapi.json",
        },
        "tip": "Se der 404, reinicie o uvicorn e confirme a porta (8080, 9080, etc.).",
    }
    health = {"status": "ok"}
    recognize_req = {
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/w8AAn8B9pO6jQAAAABJRU5ErkJggg==",
        "camera_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    }
    recognize_res = {
        "matched": False,
        "person_id": None,
        "person_name": None,
        "score": None,
        "model_name": "stub",
    }
    gate_req = {
        "reason": "visita",
        "token": "opcional-assinatura-desktop",
    }
    gate_res = {
        "accepted": True,
        "message": "Comando aceite (demonstração).",
    }
    camera_status = {
        "online": True,
        "last_seen_utc": "2026-04-25T12:00:00+00:00",
        "last_error": None,
    }
    camera_item = {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "name": "Entrada principal",
        "ip_address": "192.168.1.100",
        "http_port": 80,
        "rtsp_url": "rtsp://192.168.1.100:554/Streaming/Channels/101",
        "onvif_endpoint": "http://192.168.1.100:80/onvif/device_service",
        "is_enabled": True,
        "last_seen_utc": "2026-04-25T10:00:00+00:00",
    }
    camera_create = {
        "name": "Entrada",
        "ip_address": "192.168.1.100",
        "http_port": 80,
        "rtsp_url": "rtsp://192.168.1.100:554/stream1",
    }
    ws_info = {
        "path": "/ws/events",
        "note": "Ligue com cliente WebSocket (não basta abrir no browser como HTML).",
        "primeiro_evento_tipo": "server.hello",
    }


class EndpointsInfo(BaseModel):
    painel: str = Field("/painel", description="Página de boas-vindas com botões (abrir no browser).")
    gravacoes: str = Field(
        "/static/painel/gravacoes.html",
        description="Painel · visualizar gravações (ficheiro estático; também `/painel/gravacoes` se a API estiver actualizada).",
    )
    docs: str = Field("/docs", description="Swagger UI (documentação e testes).")
    redoc: str = Field("/redoc", description="ReDoc (leitura contínua).")
    health: str = Field("/health", description="Verificação de saúde (`GET /health`).")
    openapi: str = Field("/openapi.json", description="Esquema OpenAPI (JSON).")

    model_config = ConfigDict(
        json_schema_extra={
            "example": _Examples.root["endpoints"],
        }
    )


class RootResponse(BaseModel):
    service: str = Field(..., description="Nome do serviço.")
    neovision_api_build: str = Field(..., description="Identificador de build (diagnóstico).")
    endpoints: EndpointsInfo = Field(..., description="URLs úteis no mesmo anfitrião e porta.")
    tip: str = Field(..., description="Dica quando algo falha a responder.")

    model_config = ConfigDict(json_schema_extra={"example": _Examples.root})


class HealthResponse(BaseModel):
    status: str = Field(
        "ok",
        description='Estado do processo. Valor típico: `"ok"`.',
    )

    model_config = ConfigDict(json_schema_extra={"example": _Examples.health})


class ServerClockResponse(BaseModel):
    utc_iso: str = Field(..., description="Hora UTC ISO 8601 (servidor NeoVision).")
    local_iso: str = Field(..., description="Hora local ISO 8601 (fuso do servidor).")
    timezone_name: str = Field(..., description="Etiqueta amigável do fuso (servidor).")


class PhysicalDiskItem(BaseModel):
    device_id: int = Field(..., description="Identificador físico (DeviceId no Windows).")
    friendly_name: str = Field("", description="Nome / modelo apresentado pelo sistema.")
    media_type: str = Field("", description="HDD, SSD, Unspecified, etc.")
    size_bytes: int = Field(0, description="Capacidade reportada em bytes.")
    health_status: str = Field(
        "",
        description="Saúde segundo o armazenamento (Healthy, Warning, Unhealthy, Unknown).",
    )
    operational_status: str = Field("", description="Estado operacional (Online, etc.).")
    bus_type: str = Field("", description="SATA, NVMe, SAS, …")
    serial_number: str | None = Field(None, description="Número de série, se disponível.")
    unique_id: str | None = Field(None, description="ID único da instância física.")


class StorageDiskListResponse(BaseModel):
    platform_supported: bool = Field(..., description="True se a enumeração existe nesta plataforma.")
    disks: list[PhysicalDiskItem] = Field(default_factory=list)
    error: str | None = Field(None, description="Motivo curto se falhou (não expor segredos).")


class PhysicalDiskDetailResponse(BaseModel):
    device_id: int
    disk: dict[str, Any] = Field(default_factory=dict, description="Propriedades do Get-PhysicalDisk (JSON).")
    reliability: dict[str, Any] | None = Field(
        None,
        description="Contadores de fiabilidade (temperatura, erros, uso NVMe, …) se o SO expuser.",
    )


class RecordingFileBrowseItem(BaseModel):
    relative_path: str = Field(..., description="Relativo ao directório NeoVision recordings (servidor API).")
    modified_utc: str
    size_bytes: int = Field(..., ge=0)
    watch_query: str = Field(
        ...,
        description="Parâmetro `rel` para GET /recordings/watch (já codificado em URL).",
    )


class RecognizeRequest(BaseModel):
    image_base64: str = Field(
        ...,
        description="Imagem em Base64 (sem o prefixo `data:...;base64,`).",
        json_schema_extra={"example": _Examples.recognize_req["image_base64"]},
    )
    camera_id: str | None = Field(
        None,
        description="ID opcional da câmera (UUID).",
        json_schema_extra={"example": _Examples.recognize_req["camera_id"]},
    )

    model_config = ConfigDict(json_schema_extra={"example": _Examples.recognize_req})


class RecognizeResponse(BaseModel):
    matched: bool = Field(..., description="Indica se houve reconhecimento.")
    person_id: str | None = Field(None, description="ID da pessoa, se existir no cadastro.")
    person_name: str | None = Field(None, description="Nome de exibição, se houver correspondência.")
    score: float | None = Field(None, description="Confiança da correspondência, se houver.")
    model_name: str = Field("stub", description="Nome do modelo de IA utilizado.")

    model_config = ConfigDict(json_schema_extra={"example": _Examples.recognize_res})


class GateOpenRequest(BaseModel):
    reason: str | None = Field(
        None,
        description="Motivo da abertura (opcional).",
        json_schema_extra={"example": _Examples.gate_req["reason"]},
    )
    token: str | None = Field(
        None,
        description="Token ou assinatura do desktop ou app, se usado.",
        json_schema_extra={"example": _Examples.gate_req["token"]},
    )

    model_config = ConfigDict(json_schema_extra={"example": _Examples.gate_req})


class GateOpenResponse(BaseModel):
    accepted: bool = Field(..., description="Indica se o comando foi aceite.")
    message: str = Field("", description="Mensagem explicativa.")

    model_config = ConfigDict(json_schema_extra={"example": _Examples.gate_res})


class CameraStatusResponse(BaseModel):
    model_config = ConfigDict(
        title="Resposta de estado (uma câmara)",
        json_schema_extra={"example": _Examples.camera_status},
    )

    online: bool = Field(
        ...,
        title="A câmara deu sinal de vida?",
        description=(
            "**Com** `?probe=true` (padrão): procura alcançar o **RTSP** e devolve *sim* se abriu o fluxo. "
            "**Com** `?probe=false`: *sim* se o registo estiver ativo, **sem** testar a rede."
        ),
    )
    last_seen_utc: str | None = Field(
        None,
        title="Quando se viu a câmara (UTC, ISO 8601)",
        description="Último `last_seen` na base, ou a hora do teste de vídeo se este for bem sucedido.",
    )
    last_error: str | None = Field(
        None,
        title="Nota / erro (texto claro)",
        description="Vazio se tudo correr bem. Caso contrário, explica (ex.: falta de `rtsp_url`, timeout, rede inacessível).",
    )


class CameraListItem(BaseModel):
    id: str = Field(
        ...,
        title="ID da câmara",
        description="Código único (UUID). É este valor que pões no endereço **Obter estado** (`/cameras/este-id/status`).",
    )
    name: str = Field(..., title="Nome", description="Nome amigável (ex.: «Portão»).")
    ip_address: str = Field(
        ...,
        title="IP na rede",
        description="Endereço IPv4 ou IPv6 da câmara, como vês no router ou no fabricante.",
    )
    http_port: int | None = Field(
        None,
        title="Porta HTTP/ONVIF",
        description="Geralmente 80, 8000 ou 8080, conforme a câmara.",
    )
    rtsp_url: str | None = Field(
        None,
        title="Endereço RTSP (vídeo)",
        description="Formato `rtsp://...` (muitas vezes com user e password). Se estiver vazio, o teste de vídeo não corre.",
    )
    onvif_endpoint: str | None = Field(
        None,
        title="Endereço ONVIF (opcional)",
        description="Se usares o descobrimento no app de mesa, este campo pode estar preenchido.",
    )
    is_enabled: bool = Field(
        ..., title="Ativa", description="Se falso, a câmara fica ignorada na lógica de monitorização."
    )
    last_seen_utc: str | None = Field(
        None,
        title="Última vez vista (UTC)",
        description="Preenchido pelo sistema (ex. último contacto ONVIF) quando existir; pode estar vazio.",
    )

    model_config = ConfigDict(
        title="Câmara (lista)",
        json_schema_extra={"example": _Examples.camera_item},
    )


class CameraCreateRequest(BaseModel):
    name: str | None = Field(
        None,
        title="Nome (opcional)",
        description="Se vazio, o sistema usa um nome automático: «Câmara» + o IP (ex. «Câmara 192.168.1.100»).",
        max_length=128,
    )
    ip_address: str = Field(
        ...,
        title="IP da câmara",
        description="Obrigatório. Ex.: `192.168.1.100` (IPv4) ou o IPv6 fornecido pelo equipamento.",
        examples=["192.168.1.100"],
    )
    http_port: int | None = Field(
        80,
        title="Porta web",
        description="Porta usada para HTTP/ONVIF (80 é o mais comum; usa null para «sem porta explícita»).",
    )
    rtsp_url: str | None = Field(
        None,
        title="URL RTSP (recomendado para teste de vídeo)",
        description="Cópia do manual do fabricante ou do NVR. Sem isto, podes ainda adicionar a câmara, mas o teste de stream não liga.",
        max_length=512,
    )
    onvif_endpoint: str | None = Field(
        None, title="URL ONVIF (opcional)", max_length=512
    )
    is_enabled: bool = Field(True, title="Ativa de imediato")

    model_config = ConfigDict(
        title="Novo registo (IP)",
        json_schema_extra={"example": _Examples.camera_create},
    )


class CameraCreateResponse(BaseModel):
    id: str = Field(
        ..., title="ID que acabou de ser criado", description="Grava este UUID para o botão de estado e para integrações."
    )
    message: str = Field(
        default="Câmara registada com sucesso.",
        title="Mensagem",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "message": "Câmara registada com sucesso.",
            }
        }
    )


class NetworkDiscoveredCamera(BaseModel):
    """Resposta de WS-Discovery (mesma VLAN / UDP 3702)."""

    onvif_endpoint: str = Field(
        ...,
        description="Primeira XAddr típica (serviço de dispositivo ONVIF).",
    )
    xaddrs: list[str] = Field(default_factory=list, description="Todos os endereços anunciados.")
    scopes: str | None = Field(None, description="Scopes ONVIF opcionais (fabricante/modelo).")
    remote_ip: str | None = Field(
        None, description="IP de origem do pacote UDP (resposta)."
    )
    ip_hint: str | None = Field(
        None,
        description="Host útil para o formulário: extraído da URL ou igual a `remote_ip`.",
    )

    model_config = ConfigDict(
        title="Câmara descoberta na rede",
        json_schema_extra={
            "example": {
                "onvif_endpoint": "http://192.168.1.64/onvif/device_service",
                "xaddrs": ["http://192.168.1.64/onvif/device_service"],
                "scopes": None,
                "remote_ip": "192.168.1.64",
                "ip_hint": "192.168.1.64",
            }
        },
    )


class WebSocketInfoResponse(BaseModel):
    path: str = Field(..., description="Path a usar com o protocolo WebSocket (mesmo anfitrião e porta).")
    note: str = Field(..., description="Como testar (browser não abre WebSocket sozinho como página).")
    primeiro_evento_tipo: str = Field(
        ...,
        description="Tipo JSON do primeiro objecto que o servidor costuma enviar (esboço).",
    )

    model_config = ConfigDict(json_schema_extra={"example": _Examples.ws_info})


def get_root_data() -> dict[str, object]:
    r = _Examples.root
    return {
        "service": r["service"],
        "neovision_api_build": r["neovision_api_build"],
        "endpoints": {**r["endpoints"]},
        "tip": r["tip"],
    }


# ---------------------------------------------------------------------------
# Estado mínimo; câmeras: MySQL (tabela `cameras`) e variáveis NEOVISION_MYSQL_*
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    register: dict[str, str] = field(
        default_factory=dict
    )  # person_id (hex) -> display_name stub


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    import importlib.util
    import pathlib

    from app import storage

    r = storage.recordings_dir()
    r.mkdir(parents=True, exist_ok=True)
    spec_main = importlib.util.find_spec("app.main")
    main_path = (
        pathlib.Path(spec_main.origin).resolve()
        if spec_main and spec_main.origin
        else pathlib.Path("(app.main não localizado)")
    )
    print("NeoVision AI: serviço pronto. No browser: /painel (botões)  ·  JSON: GET /")
    print(f"  app.main carregado de: {main_path}")
    print(f"  Pasta de gravações (dados): {r}")
    print("  (Override: variável de ambiente NEOVISION_DATA_DIR; Linux: XDG_DATA_HOME / ~/.local/share)")
    yield


app = FastAPI(
    title="NeoVision AI",
    version="0.1.0",
    description=(
        "API local: IA, câmeras e automação. Resumos e tags em **pt-BR**.\n\n"
        "O **WebSocket** em `/ws/events` **não** é listado como operação HTTP — use um cliente WebSocket.\n\n"
        "**Dica:** desative a **tradução automática** da página se «pegar»/«aplicativo/json» aparecerem. "
        "Try it out / Execute são do Swagger (inglês)."
    ),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "metadados",
            "description": "Atalhos: JSON na raiz e ligação para a documentação.",
        },
        {
            "name": "sistema",
            "description": "A API neste computador a correr: **GET /health**, **GET /system/clock** (hora do servidor), **GET /system/storage/disks** e detalhe por **device_id** no Windows (PowerShell, resumo de saúde dos discos — não substitui ferramentas SMART completas).",
        },
        {
            "name": "Câmeras",
            "description": (
                "#### O que fazer na prática\n\n"
                "1. **Registar** uma câmara: **IP** (obrigatório), resto é opcional (nome, porta web, `rtsp://...`).\n"
                "2. **Listar** para obter o **id** (UUID) de cada uma — é esse código que pões no endereço seguinte.\n"
                "3. **Ver se responde**: usa o *id* no URL de estado; por defeito a API **tenta o vídeo RTSP** (pode demorar alguns segundos).\n\n"
                "Os mesmos dados existem no **app de mesa** (descoberta ONVIF) e partilham a **tabela** `cameras` no MySQL."
            ),
        },
        {
            "name": "ia",
            "description": "Reconhecimento facial a partir de imagem (Base64).",
        },
        {
            "name": "automação",
            "description": "Portão, alarme e outras ações.",
        },
    ],
)


def _custom_openapi() -> dict[str, Any]:
    """OpenAPI sem GET /ws/events (evita confusão) e sem 422 nas operações (menos ruído no Swagger)."""
    if app.openapi_schema is not None:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    for path_item in openapi_schema.get("paths", {}).values():
        for key, op in list(path_item.items()):
            if key == "parameters" or not isinstance(op, dict):
                continue
            resp = op.get("responses")
            if isinstance(resp, dict) and "422" in resp:
                del resp["422"]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = _custom_openapi


@app.get(
    "/",
    response_model=RootResponse,
    response_model_exclude_none=False,
    summary="Página inicial ou JSON da API",
    description=(
        "**Navegador:** o pedido traz `Accept: text/html` → resposta **302** para `/painel` (botões para abrir o sistema). "
        "**curl, Postman, código:** recebe o JSON (links em `endpoints`, incl. `painel`)."
    ),
    tags=["metadados"],
    responses={302: {"description": "Redirecionamento para `/painel` (botões)."}},
)
def root(request: Request) -> RootResponse | RedirectResponse:
    accept = (request.headers.get("accept") or "").lower()
    if "text/html" in accept:
        return RedirectResponse(url="/painel", status_code=302)
    return RootResponse.model_validate(get_root_data())


@app.get(
    "/app",
    include_in_schema=False,
)
def root_browser_help() -> RedirectResponse:
    return RedirectResponse(url="/painel", status_code=302)


def _read_painel_file(filename: str) -> HTMLResponse:
    root = (package_root() / "static" / "painel").resolve()
    f = (root / filename).resolve()
    try:
        f.relative_to(root)
    except ValueError as e:
        raise HTTPException(
            status_code=404, detail="Página inválida."
        ) from e
    if not f.is_file():
        raise HTTPException(status_code=404, detail="Página não encontrada.")
    return HTMLResponse(
        f.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8"
    )


PAINEL_SECCOES: dict[str, str] = {
    "sistema": "sistema.html",
    "ia": "ia.html",
    "automacao": "automacao.html",
    "cameras": "cameras.html",
    "adicionar-camera": "adicionar-camera.html",
    "gravacoes": "gravacoes.html",
    "tempo-real": "tempo-real.html",
}


@app.get(
    "/painel",
    include_in_schema=False,
    response_class=HTMLResponse,
    summary="Dashboard (painel) com acesso às secções",
)
def painel_inicio() -> HTMLResponse:
    return _read_painel_file("index.html")


@app.get(
    "/painel/gravacoes",
    include_in_schema=False,
    summary="Gravações → ficheiro estático (funciona mesmo em builds antigos se o .html existir).",
)
def painel_gravacoes_explicit() -> RedirectResponse:
    """Redirecciona para `/static/…` para não depender apenas do mapa de secções."""
    return RedirectResponse(url="/static/painel/gravacoes.html", status_code=302)


@app.get(
    "/painel/{section}",
    include_in_schema=False,
    response_class=HTMLResponse,
    summary="Uma secção do painel (Sistema, IA, …)",
)
def painel_secao(section: str) -> HTMLResponse:
    s = (section or "").strip().lower()
    # Alias com acento (URL pode ser /painel/gravações).
    if s == "gravações":
        s = "gravacoes"
    name = PAINEL_SECCOES.get(s)
    if name is None:
        secs = ", ".join(sorted(PAINEL_SECCOES.keys()))
        raise HTTPException(
            status_code=404,
            detail=f"Secção inexistente. Secções válidas: {secs}.",
        )
    if name == "gravacoes.html":
        return RedirectResponse(url="/static/painel/gravacoes.html", status_code=302)
    return _read_painel_file(name)


def _decode_image_b64(b64: str) -> Any:
    """OpenCV e numpy só aqui — a API (health) arranca mesmo se cv2 estiver a falhar."""
    import cv2
    import numpy as np

    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("imagem inválida ou não suportada")
    return img


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["sistema"],
    summary="Verificação de saúde (teste de vida)",
    description="Resposta mínima para monitorização e para o teste de ligação no app de mesa. Caminho: **`/health`** (não use acentos no URL).",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


def _normalize_disk_row(row: dict[str, Any]) -> PhysicalDiskItem:
    sr = row.get("serial_number")
    uid = row.get("unique_id")
    return PhysicalDiskItem(
        device_id=int(row.get("device_id", -1)),
        friendly_name=str(row.get("friendly_name") or ""),
        media_type=str(row.get("media_type") or ""),
        size_bytes=int(row.get("size_bytes") or 0),
        health_status=str(row.get("health_status") or ""),
        operational_status=str(row.get("operational_status") or ""),
        bus_type=str(row.get("bus_type") or ""),
        serial_number=None if sr in (None, "") else str(sr),
        unique_id=None if uid in (None, "") or str(uid).strip() == "" else str(uid),
    )


@app.get(
    "/system/clock",
    response_model=ServerClockResponse,
    tags=["sistema"],
    summary="Relógio do servidor (NeoVision)",
    description="Útil para alinhar diagnóstico com outros logs na mesma máquina onde corre a API.",
)
def system_clock_endpoint() -> ServerClockResponse:
    from app import system_hw

    data = system_hw.server_clock()
    return ServerClockResponse(**data)


@app.get(
    "/system/storage/disks",
    response_model=StorageDiskListResponse,
    tags=["sistema"],
    summary="Listar discos físicos (HD / SSD / NVMe)",
    description=(
        "**Windows:** dados do `Get-PhysicalDisk` (saúde e estado como o Gestor de tarefas / armazenamento). "
        "Não substitui CrystalDiskInfo em profundidade SMART, mas permite ver rapidamente Healthy/Warning/Unhealthy "
        "e tipos SATA/NVMe. Noutras plataformas devolve `platform_supported=false`."
    ),
)
async def system_storage_disks_list() -> StorageDiskListResponse:
    from app import system_hw

    rows, err = await asyncio.to_thread(system_hw.list_physical_disks)
    if err == "not_windows":
        return StorageDiskListResponse(platform_supported=False, disks=[], error=None)
    if err:
        short = (err[:200] + "…") if len(err) > 200 else err
        return StorageDiskListResponse(platform_supported=True, disks=[], error=short)
    items: list[PhysicalDiskItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            items.append(_normalize_disk_row(row))
        except (KeyError, TypeError, ValueError):
            continue
    return StorageDiskListResponse(platform_supported=True, disks=items, error=None)


async def _storage_disk_detail_response(device_id: int) -> PhysicalDiskDetailResponse:
    from app import system_hw

    raw, err = await asyncio.to_thread(system_hw.physical_disk_detail, device_id)
    if err or not raw:
        raise HTTPException(
            status_code=404,
            detail="Não foi possível ler este disco (índice inválido ou PowerShell/indisponível).",
        ) from None
    rel = raw.get("reliability")
    if not isinstance(rel, dict):
        rel = None
    return PhysicalDiskDetailResponse(
        device_id=device_id,
        disk=raw.get("disk") if isinstance(raw.get("disk"), dict) else {},
        reliability=rel,
    )


@app.get(
    "/system/storage/disk",
    response_model=PhysicalDiskDetailResponse,
    tags=["sistema"],
    summary="Detalhe de um disco (query)",
    description=(
        "Igual a `/system/storage/disks/{device_id}`, por parâmetro na query — evita alguns 404 genéricos quando o "
        "trajecto com segmento numérico é bloqueado ou a build antiga só expunha a lista."
    ),
    responses={404: {"description": "Disco não encontrado ou comando falhou"}},
)
async def system_storage_disk_detail_query(
    device_id: int = Query(..., ge=0, le=1024, description="Mesmo `device_id` da listagem."),
) -> PhysicalDiskDetailResponse:
    return await _storage_disk_detail_response(device_id)


@app.get(
    "/system/storage/disks/{device_id}",
    response_model=PhysicalDiskDetailResponse,
    tags=["sistema"],
    summary="Detalhe de um disco (clique no painel)",
    description=(
        "JSON bruto das propriedades do disco + contadores `Get-StorageReliabilityCounter` quando o Windows os expõe "
        "(temperatura, erros lidos/potenciais em alguns SSD/NVMe com controlador compatível)."
    ),
    responses={404: {"description": "Disco não encontrado ou comando falhou"}},
)
async def system_storage_disk_detail(
    device_id: int = Path(..., ge=0, description="Índice `device_id` listado."),
) -> PhysicalDiskDetailResponse:
    return await _storage_disk_detail_response(device_id)


def _recordings_time_bounds(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    end_utc = (
        datetime.now(timezone.utc)
        if end is None
        else (end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc))
    )
    start_utc = (
        end_utc - timedelta(days=7)
        if start is None
        else (start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc))
    )
    if start_utc > end_utc:
        raise HTTPException(
            status_code=400,
            detail="A data/hora de início deve ser anterior ou igual ao fim do intervalo.",
        ) from None
    return start_utc, end_utc


@app.get(
    "/recordings/files",
    response_model=list[RecordingFileBrowseItem],
    tags=["Câmeras"],
    summary="Listar gravações no disco (pasta recordings da API)",
    description=(
        "Lista ficheiros de vídeo na pasta de dados `recordings` (alinhado ao NeoVision Desktop / `NEOVISION_DATA_DIR`). "
        "O filtro temporal usa a **modificação** do ficheiro. Com `camera_id`, aplicam-se correspondências pelo **nome/IP** no caminho."
    ),
)
async def list_recording_files_api(
    start: datetime | None = Query(
        None,
        description="Início do intervalo. Se omitir: 7 dias antes de `end`.",
    ),
    end: datetime | None = Query(
        None,
        description="Fim do intervalo. Se omitir: agora (UTC).",
    ),
    camera_id: str | None = Query(
        None,
        description="UUID da câmara registada para filtrar por IP/nome no caminho.",
    ),
) -> list[RecordingFileBrowseItem]:
    from app import recordings_fs
    from app import storage as storage_mod

    start_utc, end_utc = _recordings_time_bounds(start, end)
    root = storage_mod.recordings_dir()
    match_filter: Any = None

    if camera_id and camera_id.strip():
        cid = camera_id.strip()
        try:
            uid = uuid.UUID(cid)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="camera_id deve ser um UUID válido.") from e

        from app import cameras as cam_mod
        from app.db_settings import MysqlSettings

        settings = MysqlSettings.from_environ()
        if err := await asyncio.to_thread(cam_mod.mysql_ping_error, settings):
            raise _http_db503(err) from None

        row = await asyncio.to_thread(cam_mod.get_camera, settings, str(uid))
        if row is None:
            raise HTTPException(status_code=404, detail="Câmara não encontrada para este id.") from None

        def _match(item: recordings_fs.RecordingFileScan) -> bool:
            rel_l = item.relative_path_posix.lower()
            return recordings_fs.recordings_match_hint(rel_l, uid, row.name, row.ip_address)

        match_filter = _match

    def _scan() -> list[RecordingFileBrowseItem]:
        scanned = recordings_fs.list_recordings_in_range(
            root,
            start_utc=start_utc,
            end_utc=end_utc,
            match_camera_filter=match_filter,
        )
        out: list[RecordingFileBrowseItem] = []
        for r in scanned:
            qrel = quote(r.relative_path_posix, safe="")
            out.append(
                RecordingFileBrowseItem(
                    relative_path=r.relative_path_posix,
                    modified_utc=r.modified_utc.isoformat().replace("+00:00", "Z"),
                    size_bytes=r.size_bytes,
                    watch_query=f"rel={qrel}",
                )
            )
        return out

    return await asyncio.to_thread(_scan)


@app.get(
    "/recordings/watch",
    tags=["Câmeras"],
    summary="Reproduzir ficheiro de gravação (pasta recordings)",
    response_class=FileResponse,
    responses={404: {"description": "Ficheiro inexistente ou fora da pasta."}},
)
async def watch_recording_file(
    rel: str = Query(..., min_length=1, description="Caminho relativo devolvido por GET /recordings/files."),
) -> FileResponse:
    from app import recordings_fs
    from app import storage as storage_mod

    root = storage_mod.recordings_dir()
    path = recordings_fs.safe_file_under(root, rel)
    if path is None:
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado ou caminho inválido.") from None
    mt, _ = mimetypes.guess_type(path.name.lower())
    media = mt or "application/octet-stream"
    return FileResponse(
        str(path),
        media_type=media,
        filename=path.name,
        content_disposition_type="inline",
    )


@app.post(
    "/ai/recognize",
    response_model=RecognizeResponse,
    tags=["ia"],
    summary="Reconhecer rosto",
    description="Recebe uma imagem em Base64. Enquanto não houver galeria, devolve não corresponde (stub).",
)
def recognize(req: RecognizeRequest) -> RecognizeResponse | JSONResponse:
    try:
        _decode_image_b64(req.image_base64)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=400, content={"detalhe": str(e), "detail": str(e)}
        )

    # Stub: nunca reconhece até existir galeria + embeddings
    return RecognizeResponse(
        matched=False,
        person_id=None,
        person_name=None,
        score=None,
        model_name="stub",
    )


@app.post(
    "/automation/gate/open",
    response_model=GateOpenResponse,
    tags=["automação"],
    summary="Solicitar abertura do portão",
    description="Esboço: aceita o pedido; integra com hardware e regras no desktop.",
)
def open_gate(_: GateOpenRequest) -> GateOpenResponse:
    return GateOpenResponse(accepted=True, message="Comando aceite (demonstração).")


def _http_db503(err: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=f"Não foi possível ligar ao MySQL. Confirme a base, credenciais e NEOVISION_MYSQL_*. ({err})",
    )


@app.post(
    "/cameras",
    response_model=CameraCreateResponse,
    tags=["Câmeras"],
    summary="Adicionar câmara (IP + opções)",
    description=(
        "Cria um registo na base com o **endereço IP** da câmara. "
        "O **nome** é opcional (se faltar, é gerado como «Câmara 192.168.…»). "
        "Indica a **porta** web (80 é habitual) e, se souberes, a **URL RTSP** para teste de vídeo. "
        "O servidor devolve o **id** (UUID) — guarda-o para o pedido *Estado*."
    ),
    response_description="Novo `id` e confirmação em texto claro.",
)
async def create_camera(body: CameraCreateRequest) -> CameraCreateResponse:
    from app import cameras as cam_mod
    from app.db_settings import MysqlSettings

    if body.http_port is not None and not (1 <= body.http_port <= 65535):
        raise HTTPException(
            status_code=400, detail="Porta inválida: use entre 1 e 65535, ou deixe o valor por defeito."
        )

    settings = MysqlSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.mysql_ping_error, settings):
        raise _http_db503(err) from None

    ip = (body.ip_address or "").strip()
    name = (body.name or "").strip() or f"Câmara {ip}"

    def _ins() -> str:
        return cam_mod.insert_camera(
            settings,
            name=name,
            ip_address=ip,
            http_port=body.http_port,
            rtsp_url=body.rtsp_url,
            onvif_endpoint=body.onvif_endpoint,
            is_enabled=body.is_enabled,
        )

    try:
        new_id = await asyncio.to_thread(_ins)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return CameraCreateResponse(id=new_id, message="Câmara registada com sucesso. Use o `id` no pedido de estado.")


@app.get(
    "/cameras",
    response_model=list[CameraListItem],
    tags=["Câmeras"],
    summary="Listar todas as câmeras",
    description=(
        "Devolve **tudo o que está guardado** (nome, IP, portas, RTSP, ONVIF, ativo). "
        "Copia o **id** (UUID) da linha que quiseres: é esse valor em `/cameras/{id}/status` abaixo."
    ),
    response_description="Tabela lida da base de dados; pode estar vazia se ainda não registaste câmaras.",
)
async def list_cameras() -> list[CameraListItem]:
    from app import cameras as cam_mod
    from app.db_settings import MysqlSettings

    settings = MysqlSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.mysql_ping_error, settings):
        raise _http_db503(err) from None
    rows = await asyncio.to_thread(cam_mod.list_cameras, settings)
    return [CameraListItem.model_validate(vars(r)) for r in rows]


@app.get(
    "/cameras/discover/network",
    response_model=list[NetworkDiscoveredCamera],
    tags=["Câmeras"],
    summary="Procurar câmaras na rede (ONVIF WS-Discovery)",
    description=(
        "Envia Probe **SOAP** sobre **UDP multicast** `239.255.255.250:3702` e espera até `listen_seconds`. "
        "Alinhado ao descobrimento do **NeoVision Desktop**; exige servidor e equipamentos na **mesma LAN** e UDP não bloqueado."
    ),
    response_description="Lista de dispositivos com XAddr única por URL principal.",
)
async def discover_cameras_network(
    listen_seconds: float = Query(
        4.0,
        ge=1.0,
        le=15.0,
        description="Tempo máximo à escuta (probe ~4 s habitual).",
    ),
) -> list[NetworkDiscoveredCamera]:
    from app import onvif_ws_discovery as wd

    raw = await asyncio.to_thread(wd.probe_network, listen_seconds)
    return [NetworkDiscoveredCamera.model_validate(r) for r in raw]


@app.get(
    "/cameras/{camera_id}/status",
    response_model=CameraStatusResponse,
    tags=["Câmeras"],
    summary="Como é que esta câmara está? (luz verde / teste de vídeo)",
    description=(
        "Precisas do **id** (UUID) — vem de **Listar câmeras** ou de **Adicionar câmara**.\n\n"
        "• `probe=true` (padrão): a API **tenta abrir o stream RTSP** (OpenCV). Pode levar **vários segundos**. "
        "O campo *online* diz se o fluxo de vídeo abriu; *last_error* explica a falta de URL, rede, etc.\n"
        "• `probe=false`: resposta imediata, **só a partir do registo** (útil se não quiseres teste de rede).\n"
    ),
    response_description="Três campos: se vai vídeo, última data/hora, e mensagem de apoio ou de erro.",
)
async def camera_status(
    camera_id: str = Path(
        ...,
        title="ID da câmara (UUID completo)",
        description=(
            "Cole aqui o identificador **exatamente** como na lista, com hífens. "
            "Não confundas com o IP: o *id* é o código extenso, não 192.168.…"
        ),
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
    probe: bool = Query(
        True,
        title="Fazer teste de vídeo (RTSP)?",
        description="**Sim (recomendado** para “está tudo bem?”) — a API liga-se ao `rtsp_url` da câmara. **Não** — resposta imediata sem abrir a rede.",
    ),
) -> CameraStatusResponse:
    try:
        uid = uuid.UUID(camera_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="camera_id inválido; use um UUID (ex.: 3fa85f64-...)."
        ) from e

    from app import cameras as cam_mod
    from app.db_settings import MysqlSettings

    settings = MysqlSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.mysql_ping_error, settings):
        raise _http_db503(err) from None

    row = await asyncio.to_thread(cam_mod.get_camera, settings, str(uid))
    if row is None:
        raise HTTPException(status_code=404, detail="Câmara inexistente para este id.")

    if not row.is_enabled:
        return CameraStatusResponse(
            online=False,
            last_seen_utc=row.last_seen_utc,
            last_error="Câmara desativada em `cameras.is_enabled`.",
        )

    if not probe:
        return CameraStatusResponse(
            online=True,
            last_seen_utc=row.last_seen_utc,
            last_error="Teste de stream RTSP não executado; omita `probe` ou use `?probe=true`.",
        )

    if not row.rtsp_url:
        return CameraStatusResponse(
            online=False,
            last_seen_utc=row.last_seen_utc,
            last_error="Defina `rtsp_url` na tabela `cameras` (ou no desktop) para testar a ligação.",
        )

    ok, perr = await asyncio.to_thread(cam_mod.probe_rtsp, row.rtsp_url, 5.0)
    if ok:
        return CameraStatusResponse(
            online=True,
            last_seen_utc=datetime.now(timezone.utc).isoformat(),
            last_error=None,
        )
    return CameraStatusResponse(
        online=False,
        last_seen_utc=row.last_seen_utc,
        last_error=perr,
    )


@app.get(
    "/ws/events",
    response_model=WebSocketInfoResponse,
    include_in_schema=False,
    summary="(não listado no OpenAPI) informação WebSocket vía HTTP",
    description="Permanece disponível em HTTP se precisar; o Swagger **não** mostra para não confundir com WebSocket.",
)
def ws_events_openapi_hint() -> WebSocketInfoResponse:
    return WebSocketInfoResponse(
        path="/ws/events",
        note="Abra com protocolo `ws://` (mesmo anfitrião e porta). O Swagger em HTTP mostra o JSON; o eco em tempo real é via WebSocket.",
        primeiro_evento_tipo="server.hello",
    )


@app.websocket(
    "/ws/events",
    name="eventos_tempo_real",
)
async def events_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "server.hello",
                    "utc": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        while True:
            # eco simples; desktop enviará heartbeats no futuro
            msg: dict[str, Any] = await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "ack",
                    "echo": msg,
                }
            )
    except WebSocketDisconnect:
        return


# --- Documentação: tema com fonte Inter + cores NeoVision (ficheiro static/docs-ui.css) ---
_static = package_root() / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui() -> HTMLResponse:
    r = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} · API",
        swagger_ui_parameters={
            "docExpansion": "none",
            "defaultModelsExpandDepth": -1,
            "defaultModelExpandDepth": 0,
            "filter": True,
            "tryItOutEnabled": True,
            "displayRequestDuration": True,
            "showExtensions": False,
            "showCommonExtensions": False,
        },
        swagger_css_url="/static/docs-ui.css",
    )
    # Evita o Chrome a traduzir «GET/POST» e «application/json» (ruído em pt machine-translate).
    body = r.body.decode("utf-8")
    if "<head>" in body:
        body = body.replace(
            "<head>",
            '<head><meta name="google" content="notranslate">',
            1,
        )
    return HTMLResponse(content=body, status_code=r.status_code, media_type=r.media_type)


@app.get("/redoc", include_in_schema=False)
async def custom_redoc() -> HTMLResponse:
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} · ReDoc",
        redoc_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
    )


# Permite: uvicorn app.main:app --reload --port 8080
def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
