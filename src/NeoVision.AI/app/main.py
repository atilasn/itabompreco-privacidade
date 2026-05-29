"""NeoVision AI — serviço HTTP/WebSocket (OpenAPI em /contracts no repositório)."""

from __future__ import annotations

import asyncio
import os
import base64
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from urllib.parse import quote

import mimetypes
import pathlib


from app.paths import package_root
from fastapi import FastAPI, HTTPException, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, FileResponse, Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool
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
        "protocolo": "RTSP",
        "canal_local": "1",
        "canal_remoto": "101",
        "porta_tcp_midia": 554,
        "buffer_segundos": 2.0,
        "tipo_pagina": "Principal",
        "numero_serie": "SN123",
        "dispositivo": "NVR Dahua",
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
        description="Painel · visualizar gravações (ficheiro estático; também `/painel/gravacoes` se a API estiver atualizada).",
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


MonitorHubScopeLiteral = Literal["local", "online"]


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
    quedas: int = Field(
        0,
        ge=0,
        description="Vezes que o stream RTSP falhou após estar OK (teste periódico em segundo plano).",
    )
    protocolo: str | None = Field(None, description="Protocolo de vídeo configurado no registo.")
    canal_local: str | None = Field(None, description="Índice ou nome do canal na origem.")
    canal_remoto: str | None = Field(None, description="Canal no NVR / stream remoto (ex.: 101).")
    porta_tcp_midia: int | None = Field(
        None,
        description="Porta TCP do stream (ex.: 554 RTSP), quando guardada no registo.",
    )
    buffer_segundos: float | None = Field(None, description="Tampão de leitura em segundos (metadado).")
    tipo_pagina: str | None = Field(None, description="Tipo de página / sub-stream (metadado).")
    numero_serie: str | None = Field(None, description="Número de série indicado no registo.")
    dispositivo: str | None = Field(
        None,
        description="Modelo ou designação do equipamento (campos modelo/fabricante agregados).",
    )
    monitor_hub_scope: MonitorHubScopeLiteral = Field(
        "local",
        description="local = câmara na rede interna; online = monitorização remota (Internet).",
    )

    model_config = ConfigDict(
        title="Câmara (lista)",
        json_schema_extra={"example": _Examples.camera_item},
    )


class CameraCreateRequest(BaseModel):
    name: str | None = Field(
        None,
        title="Nome (opcional)",
        description="Nome do canal / câmera. Se vazio, é gerado como «Câmara» + o IP.",
        max_length=128,
    )
    ip_address: str = Field(
        ...,
        title="IP da câmara ou NVR",
        description="Obrigatório. Ex.: `192.168.1.100` (IPv4) ou IPv6.",
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
        description="URL completa do stream. Sem isto o teste de vídeo não liga ao vídeo.",
        max_length=512,
    )
    onvif_endpoint: str | None = Field(
        None, title="URL ONVIF (opcional)", max_length=512
    )
    is_enabled: bool = Field(True, title="Ativa de imediato")
    protocol: str | None = Field(None, description="Protocolo (RTSP, RTSPS, RTMP…).", max_length=32)
    canal_local: str | None = Field(None, description="Canal local / origem.", max_length=64)
    canal_remoto: str | None = Field(None, description="Canal remoto no NVR (ex. 101).", max_length=64)
    buffer_seconds: float | None = Field(None, ge=0, description="Tampão (segundos) — metadado.")
    tipo_pagina: str | None = Field(None, max_length=64, description="Tipo de página / sub-stream.")
    serial_number: str | None = Field(None, max_length=128)
    rtsp_tcp_port: int | None = Field(None, ge=1, le=65535, description="Porta TCP do stream (ex.: 554).")
    device: str | None = Field(None, max_length=64, description="Modelo ou tipo de dispositivo (NVR, câmara IP…).")
    rtsp_path: str | None = Field(
        None,
        max_length=256,
        description="Caminho do stream (ex. /stream1). Usado se não preencher rtsp_url completo.",
    )
    rtsp_username: str | None = Field(None, max_length=128, description="Utilizador RTSP (montagem automática da URL).")
    rtsp_password: str | None = Field(None, max_length=256, description="Senha RTSP (montagem automática da URL).")
    monitor_hub_scope: MonitorHubScopeLiteral | None = Field(
        None,
        description="local (padrão se omitido) ou online. Na actualização (PUT), omitir para manter o valor guardado.",
    )

    model_config = ConfigDict(
        title="Novo registo (IP)",
        json_schema_extra={"example": _Examples.camera_create},
    )


class RtspProbeRequest(BaseModel):
    rtsp_url: str = Field(..., description="URL de stream (rtsp://… ou rtmp://…).", max_length=512)


class RtspProbeResponse(BaseModel):
    online: bool
    last_error: str | None = None


class OnvifMediaProfilesRequest(BaseModel):
    """Credenciais HTTP/ONVIF no dispositivo para listar perfis e URIs RTSP."""

    ip_address: str = Field(..., description="IPv4/IPv6 ou hostname da câmera.")
    http_port: int = Field(80, ge=1, le=65535, description="Porta HTTP/ONVIF (80 habitual).")
    username: str = Field("", description="Utilizador ONVIF.")
    password: str = Field("", description="Senha ONVIF.")


class OnvifMediaProfileRow(BaseModel):
    token: str = Field("", description="Token do perfil no dispositivo.")
    name: str = Field("", description="Nome ou etiqueta ONVIF.")
    rtsp_uri: str = Field("", description="URL RTSP devolvida por GetStreamUri (se existir).")
    warning: str | None = Field(None, description="Erro só desse perfil (ex.: stream não disponível).")


EstadoEquipamentoLiteral = Literal["online", "offline", "sem_dados"]

IconEquipamentoLiteral = Literal[
    "generic",
    "switch",
    "router",
    "camera",
    "wifi",
    "server",
    "firewall",
    "printer",
    "nas",
    "access_point",
    "site",
]


class NetworkEquipmentMonitorItem(BaseModel):
    id: str
    nome: str
    ip_ou_dns: str = Field("", description="IP ou nome (ICMP); ignorado para o teste se houver URL HTTP.")
    intervalo_segundos: int = Field(..., ge=10, description="Verificação no máximo uma vez por este período.")
    monitor_ativo: bool
    icon_kind: IconEquipamentoLiteral = Field(
        "generic",
        description="Ícone escolhido na área visual (tipo de equipamento).",
    )
    estado: EstadoEquipamentoLiteral
    tempo_actual_estado_segundos: float | None = Field(
        None,
        description="Tempo corrido desde a última mudança Online/Offline (segundos).",
    )
    total_online_segundos: int = Field(
        ...,
        ge=0,
        description="Total acumulado no estado ligado desde o registo (aprox.).",
    )
    total_offline_segundos: int = Field(
        ...,
        ge=0,
        description="Total acumulado no estado Offline desde o registo (aprox.).",
    )
    quedas: int = Field(
        0,
        ge=0,
        description="Número de vezes que o equipamento passou de online a offline (ICMP ou HTTP).",
    )
    ultima_verificacao_utc: str | None
    url_painel_dvr: str | None = Field(
        None,
        max_length=512,
        description=(
            "URL da interface web (ex. http://10.100.103.8:8008/). "
            "Entrada sem pedir utilizador apenas em equipamentos com HTTP Basic Auth."
        ),
    )
    usuario_painel_dvr: str | None = Field(None, max_length=128)
    senha_painel_dvr: str | None = Field(
        None,
        max_length=256,
        description="Guardada em texto na base local; apenas para LAN de confiança.",
    )
    http_monitor_url: str | None = Field(
        None,
        max_length=2048,
        description=(
            "Se preenchido, o monitor faz GET a este URL (porta e caminho incluídos) em vez de ICMP. "
            "Ex.: http://189.50.50.253:8000/doc/index.html — útil quando o equipamento não responde a ping."
        ),
    )
    monitor_hub_scope: MonitorHubScopeLiteral = Field(
        "local",
        description="local = monitorização na rede interna; online = equipamentos / URLs remotos (Internet).",
    )


class NetworkEquipmentUpsert(BaseModel):
    nome: str = Field("", max_length=128)
    ip_address: str = Field(..., description="IPv4 / IPv6 ou hostname (UniFi, switch…).")
    poll_interval_seconds: int = Field(60, ge=10, le=86400)
    is_enabled: bool = Field(True)
    icon_kind: IconEquipamentoLiteral = Field(
        "generic",
        description="Ícone na vista em grelha (switch, router, câmera, …).",
    )
    url_painel_dvr: str | None = Field(None, max_length=512)
    usuario_painel_dvr: str | None = Field(None, max_length=128)
    senha_painel_dvr: str | None = Field(None, max_length=256)
    http_monitor_url: str | None = Field(
        None,
        max_length=2048,
        description="Opcional: verificação HTTP (GET) em vez de ping ICMP ao IP.",
    )
    monitor_hub_scope: MonitorHubScopeLiteral | None = Field(
        None,
        description=(
            "local = rede interna; online = Internet. Na criação, omitir = local. "
            "Na actualização (PUT), omitir para não alterar o âmbito."
        ),
    )


class NetworkEquipmentCreatedResponse(BaseModel):
    id: str


class NetworkEquipmentBackupPayload(BaseModel):
    format: Literal["neovision-network-equipment"] = Field(
        "neovision-network-equipment",
        description="Identificador do ficheiro de backup JSON.",
    )
    version: int = Field(1, ge=1, le=1)
    exported_utc: str | None = Field(None, description="ISO 8601 UTC quando foi gerado (opcional).")
    hosts: list[NetworkEquipmentUpsert] = Field(
        default_factory=list,
        max_length=2048,
        description="Lista de equipamentos a gravar / restaurar.",
    )


class NetworkEquipmentBackupImportBody(BaseModel):
    replace_all: bool = Field(
        False,
        description="Se verdadeiro, apaga **todos** os equipamentos antes de importar (útil em PC novo).",
    )
    data: NetworkEquipmentBackupPayload


class NetworkEquipmentBackupImportResult(BaseModel):
    inserted: int = Field(..., ge=0)
    updated: int = Field(..., ge=0)
    replaced_all: int = Field(..., ge=0, le=1)


class LanPingScanHostItem(BaseModel):
    ip: str
    alive: bool
    latency_ms: float | None = Field(None, description="Tempo aproximado lido na saída do ping.")
    hostname: str | None = Field(None, description="Resolução PTR (opcional); pode ficar em branco.")


class LanPingScanResponse(BaseModel):
    cidr_note: str = Field("", description="Resumo das redes ou CIDR usado.")
    total_ips: int
    alive_count: int
    duration_sec: float
    results: list[LanPingScanHostItem]


class WifiSurveyBssidItem(BaseModel):
    ssid: str = Field("", description="Nome da rede (vazio se oculta).")
    bssid: str = Field(..., description="MAC do ponto de acesso (BSSID).")
    signal_pct: int | None = Field(None, description="Intensidade aproximada 0–100%.")
    channel: int | None = Field(None, description="Canal Wi‑Fi reportado.")
    radio_type: str | None = Field(None, description="Ex.: 802.11ax.")
    band: str | None = Field(None, description="Ex.: 2.4 GHz / 5 GHz.")
    authentication: str | None = None
    encryption: str | None = None
    vendor: str | None = Field(None, description="Fabricante estimado pelo prefixo OUI do MAC.")
    ap_hint: str | None = Field(None, description="Dica: ex. provável AP UniFi / Ubiquiti.")


class WifiSurveyResponse(BaseModel):
    platform_supported: bool = Field(
        ...,
        description="False fora do Windows; no Windows True mesmo se não houver interface Wi‑Fi.",
    )
    error: str | None = Field(None, description="Motivo curto se a leitura falhou.")
    note: str | None = Field(None, description="Contexto ou dica ao utilizador.")
    networks: list[WifiSurveyBssidItem]


class CameraCreateResponse(BaseModel):
    id: str = Field(
        ...,
        title="ID que acabou de ser criado",
        description="Grava este UUID para o botão de estado e para integrações.",
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
    """Resultado combinado: ONVIF WS-Discovery ou varrimento TCP (câmaras IP genéricas)."""

    onvif_endpoint: str | None = Field(
        None,
        description="Serviço de dispositivo ONVIF (XAddr); omisso apenas em modo varrimento só-IP.",
    )
    xaddrs: list[str] = Field(default_factory=list, description="Todos os endereços ONVIF anunciados.")
    scopes: str | None = Field(None, description="Scopes ONVIF ou texto sobre portas encontradas.")
    remote_ip: str | None = Field(None, description="IP de origem (UDP WS-Discovery) ou alvo TCP.")
    ip_hint: str | None = Field(
        None,
        description="Host para preencher o formulário: extraído da URL OU igual ao IP analisado.",
    )
    discovery_source: Literal["onvif", "ip"] = Field(
        ...,
        description="Origem da linha: `onvif` (multicast UDP) ou `ip` (portas TCP comuns na LAN).",
    )
    open_ports: list[int] = Field(default_factory=list, description="Portas TCP abertas (apenas modo `ip`).")

    model_config = ConfigDict(
        title="Câmara descoberta na rede",
        json_schema_extra={
            "example": {
                "onvif_endpoint": "http://192.168.1.64/onvif/device_service",
                "xaddrs": ["http://192.168.1.64/onvif/device_service"],
                "scopes": None,
                "remote_ip": "192.168.1.64",
                "ip_hint": "192.168.1.64",
                "discovery_source": "onvif",
                "open_ports": [],
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


# --- Mapeamento câmeras (SQLite/MySQL) → resposta lista ---
from app.cameras import CameraRow


def _extras_dict_from_camera_create(body: CameraCreateRequest) -> dict[str, Any] | None:
    acc: dict[str, Any] = {}
    if body.protocol and str(body.protocol).strip():
        acc["protocol"] = str(body.protocol).strip()[:32]
    if body.canal_local and str(body.canal_local).strip():
        acc["local_channel"] = str(body.canal_local).strip()[:64]
    if body.canal_remoto and str(body.canal_remoto).strip():
        acc["remote_channel"] = str(body.canal_remoto).strip()[:64]
    if body.buffer_seconds is not None:
        acc["buffer_seconds"] = float(body.buffer_seconds)
    if body.tipo_pagina and str(body.tipo_pagina).strip():
        acc["page_type"] = str(body.tipo_pagina).strip()[:64]
    if body.serial_number and str(body.serial_number).strip():
        acc["serial_number"] = str(body.serial_number).strip()[:128]
    if body.rtsp_tcp_port is not None:
        acc["media_tcp_port"] = int(body.rtsp_tcp_port)
    return acc if acc else None


def _extras_parse(raw: str | None) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        o = json.loads(raw)
        return o if isinstance(o, dict) else {}
    except json.JSONDecodeError:
        return {}


def _device_label(row: CameraRow) -> str | None:
    a = (row.manufacturer or "").strip()
    b = (row.model or "").strip()
    if a and b:
        return f"{a} · {b}"
    return a or b or None


def camera_row_to_list_item(row: CameraRow) -> CameraListItem:
    ex = _extras_parse(row.extras_json)

    proto = ex.get("protocol")
    if not isinstance(proto, str):
        proto = None

    loc = ex.get("local_channel")
    if not isinstance(loc, str):
        loc = None

    rem = ex.get("remote_channel")
    if not isinstance(rem, str):
        rem = None

    tcp = ex.get("media_tcp_port")
    if tcp is not None:
        try:
            tcp_int = int(tcp)
            if tcp_int < 1 or tcp_int > 65535:
                tcp_int = None
        except (TypeError, ValueError):
            tcp_int = None
    else:
        tcp_int = None

    buf = ex.get("buffer_seconds")
    buf_out: float | None
    try:
        buf_out = float(buf) if buf is not None else None
    except (TypeError, ValueError):
        buf_out = None

    tipo = ex.get("page_type")
    if not isinstance(tipo, str):
        tipo = None

    ser = ex.get("serial_number")
    if not isinstance(ser, str):
        ser = None

    return CameraListItem(
        id=row.id,
        name=row.name,
        ip_address=row.ip_address,
        http_port=row.http_port,
        rtsp_url=row.rtsp_url,
        onvif_endpoint=row.onvif_endpoint,
        is_enabled=row.is_enabled,
        last_seen_utc=row.last_seen_utc,
        protocolo=proto,
        canal_local=loc,
        canal_remoto=rem,
        porta_tcp_midia=tcp_int,
        buffer_segundos=buf_out,
        tipo_pagina=tipo,
        numero_serie=ser,
        dispositivo=_device_label(row),
        quedas=max(0, int(row.offline_incidents)),
        monitor_hub_scope=(
            row.monitor_hub_scope if row.monitor_hub_scope in ("local", "online") else "local"
        ),
    )


from app.network_equipment import (
    NetworkEquipmentRow,
    dvr_painel_campos_desde_extras,
    http_monitor_url_from_extras,
    normalize_icon_kind as ne_norm_icon_kind,
)


def _network_equipment_dvr_patch(body: NetworkEquipmentUpsert) -> dict[str, Any]:
    dumped = body.model_dump(exclude_unset=True)
    patch: dict[str, Any] = {}
    mapping = {"url_painel_dvr": "url", "usuario_painel_dvr": "usuario", "senha_painel_dvr": "senha"}
    for api_k, store_k in mapping.items():
        if api_k in dumped:
            patch[store_k] = dumped[api_k]
    return patch


def _merge_network_equipment_extras(old: str | None, body: NetworkEquipmentUpsert) -> str | None:
    from app import network_equipment as ne_mod

    ej = old
    dvr_patch = _network_equipment_dvr_patch(body)
    if dvr_patch:
        ej = ne_mod.merge_network_extras_dvr_panel(ej, dvr_patch)
    dumped = body.model_dump(exclude_unset=True)
    if "http_monitor_url" in dumped:
        ej = ne_mod.set_http_monitor_in_extras(ej, body.http_monitor_url)
    return ej


def network_row_to_item(row: NetworkEquipmentRow) -> NetworkEquipmentMonitorItem:
    now = datetime.now(timezone.utc)
    ls = row.last_state
    if ls is True:
        est: EstadoEquipamentoLiteral = "online"
    elif ls is False:
        est = "offline"
    else:
        est = "sem_dados"
    seg: float | None = None
    if row.state_since_utc:
        try:
            t0 = datetime.fromisoformat(str(row.state_since_utc).replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            seg = max(0.0, (now - t0.astimezone(timezone.utc)).total_seconds())
        except ValueError:
            seg = None
    dvr = dvr_painel_campos_desde_extras(row.extras_json)
    hm = http_monitor_url_from_extras(row.extras_json)
    mhs: MonitorHubScopeLiteral = (
        row.monitor_hub_scope if row.monitor_hub_scope in ("local", "online") else "local"
    )
    return NetworkEquipmentMonitorItem(
        id=row.id,
        nome=row.label,
        ip_ou_dns=row.ip_address,
        intervalo_segundos=row.poll_interval_seconds,
        monitor_ativo=row.is_enabled,
        icon_kind=ne_norm_icon_kind(row.icon_kind),
        estado=est,
        tempo_actual_estado_segundos=seg,
        total_online_segundos=row.total_up_seconds,
        total_offline_segundos=row.total_down_seconds,
        quedas=max(0, int(row.offline_incidents)),
        ultima_verificacao_utc=row.last_check_utc,
        http_monitor_url=hm,
        monitor_hub_scope=mhs,
        **dvr,
    )


def get_root_data() -> dict[str, object]:
    r = _Examples.root
    return {
        "service": r["service"],
        "neovision_api_build": r["neovision_api_build"],
        "endpoints": {**r["endpoints"]},
        "tip": r["tip"],
    }


# ---------------------------------------------------------------------------
# Estado mínimo; câmeras: SQLite (por defeito) ou MySQL (`cameras`; NEOVISION_DB / NEOVISION_SQLITE_PATH / NEOVISION_MYSQL_*)
# ---------------------------------------------------------------------------


@dataclass
class AppState:
    register: dict[str, str] = field(
        default_factory=dict
    )  # person_id (hex) -> display_name stub


state = AppState()


async def _ip_recording_refresh_loop(interval_sec: float) -> None:
    """Sincroniza processos ffmpeg com câmaras RTSP na base (substitui DVR/NVR)."""
    await asyncio.sleep(6.0)
    from app.camera_recorder import get_recorder
    from app.db_settings import DatabaseSettings

    rec = get_recorder()
    while True:
        try:
            db = DatabaseSettings.from_environ()
            await asyncio.to_thread(rec.refresh, db)
        except Exception:
            import traceback

            traceback.print_exc()
        await asyncio.sleep(interval_sec)


async def _camera_rtsp_monitor_loop(interval_sec: float) -> None:
    await asyncio.sleep(25.0)
    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    while True:
        try:
            settings = DatabaseSettings.from_environ()
            if await asyncio.to_thread(cam_mod.db_ping_error, settings):
                await asyncio.sleep(max(45.0, interval_sec))
                continue
            rows = await asyncio.to_thread(cam_mod.list_cameras, settings)
            for row in rows:
                if not row.is_enabled:
                    continue
                u_rtsp = (row.rtsp_url or "").strip()
                if not u_rtsp:
                    continue
                ok, _ = await asyncio.to_thread(cam_mod.probe_rtsp, u_rtsp, 4.5)
                await asyncio.to_thread(cam_mod.record_rtsp_probe_result, settings, row.id, is_up=ok)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(max(45.0, interval_sec))


@asynccontextmanager
async def lifespan(_: FastAPI):
    import importlib.util
    import pathlib
    from contextlib import suppress as ctx_suppress

    from app import storage
    from app.camera_recorder import get_recorder
    from app.network_equipment import monitor_loop as net_monitor_loop

    r = storage.recordings_dir()
    r.mkdir(parents=True, exist_ok=True)
    spec_main = importlib.util.find_spec("app.main")
    main_path = (
        pathlib.Path(spec_main.origin).resolve()
        if spec_main and spec_main.origin
        else pathlib.Path("(app.main não localizado)")
    )
    raw_iv = (os.environ.get("NEOVISION_RECORD_REFRESH_SEC", "") or "45").strip()
    try:
        rec_iv = float(raw_iv.replace(",", "."))
    except ValueError:
        rec_iv = 45.0
    rec_iv = max(15.0, min(rec_iv, 3600.0))

    print("NeoVision AI: serviço pronto. No browser: /painel (botões)  ·  JSON: GET /")
    print(f"  app.main carregado de: {main_path}")
    print(f"  Pasta de gravações (dados): {r}")
    print("  (Override: variável de ambiente NEOVISION_DATA_DIR; Linux: XDG_DATA_HOME / ~/.local/share)")
    print(
        f"  Gravação RTSP (DVR/NVR): intervalo refresco {rec_iv}s · "
        "NEOVISION_RECORDING_DISABLED=1 desliga · "
        "precisa FFmpeg (PATH ou NEOVISION_FFMPEG)",
    )
    ping_bg = asyncio.create_task(net_monitor_loop(8.0))
    cam_probe_bg = asyncio.create_task(_camera_rtsp_monitor_loop(90.0))
    rec_bg = asyncio.create_task(_ip_recording_refresh_loop(rec_iv))
    yield
    rec_bg.cancel()
    with ctx_suppress(asyncio.CancelledError):
        await rec_bg
    get_recorder().stop_all()
    cam_probe_bg.cancel()
    with ctx_suppress(asyncio.CancelledError):
        await cam_probe_bg
    ping_bg.cancel()
    with ctx_suppress(asyncio.CancelledError):
        await ping_bg


app = FastAPI(
    title="NeoVision AI",
    version="0.2.0",
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
                "Os mesmos dados podem existir no **app de mesa** (descoberta ONVIF); com MySQL, partilham a tabela `cameras`; com SQLite só na API local."
            ),
        },
        {
            "name": "rede",
            "description": "**Monitorização de equipamentos** na LAN por **ping ICMP** (switches, câmaras, UniFi Controller, etc.): estado Online/Offline e tempos acumulados.",
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
    "monitoramento": "monitoramento.html",
    # URL legível = mesmo ficheiro que monitoramento (ICMP + câmeras no mapa)
    "equipamentos-rede": "monitoramento.html",
    "equipamentos_rede": "monitoramento.html",
    "escanear-rede": "escanear-rede.html",
    "mapa-wifi": "mapa-wifi.html",
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
    if s.endswith(".html"):
        s = s[: -len(".html")]
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
        from app.db_settings import DatabaseSettings

        settings = DatabaseSettings.from_environ()
        if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
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
    "/recordings/recorder",
    tags=["Câmeras"],
    summary="Estado do gravador RTSP (NeoVision DVR)",
    description=(
        "Lista processos ffmpeg activos por câmara, duração de segmentos e disponibilidade de FFmpeg. "
        "Útil para diagnóstico quando substituis um NVR: confirma se as gravações estão a rodar "
        "(câmaras activas na BD + URL RTSP + ffmpeg no PATH)."
    ),
)
async def recordings_recorder_status() -> dict[str, object]:
    from app.camera_recorder import get_recorder

    return await asyncio.to_thread(get_recorder().snapshot)


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
        detail=(
            "Não foi possível usar a base de dados (SQLite/MySQL). "
            "SQLite: permissões na pasta NeoVisionData ou NEOVISION_SQLITE_PATH; "
            "MySQL: NEOVISION_DB=mysql e NEOVISION_MYSQL_*. "
            f"({err})"
        ),
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
    from app.db_settings import DatabaseSettings

    if body.http_port is not None and not (1 <= body.http_port <= 65535):
        raise HTTPException(
            status_code=400, detail="Porta inválida: use entre 1 e 65535, ou deixe o valor por defeito."
        )

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    ip = (body.ip_address or "").strip()
    name = (body.name or "").strip() or f"Câmara {ip}"
    model_dev = ((body.device or "").strip() or None)[:64] if body.device else None
    extras = _extras_dict_from_camera_create(body)

    def _ins() -> str:
        rt_eff = cam_mod.compose_rtsp_url(
            ip,
            rtsp_url=body.rtsp_url,
            rtsp_tcp_port=body.rtsp_tcp_port,
            rtsp_path=body.rtsp_path,
            rtsp_username=body.rtsp_username,
            rtsp_password=body.rtsp_password,
        )
        return cam_mod.insert_camera(
            settings,
            name=name,
            ip_address=ip,
            http_port=body.http_port,
            rtsp_url=rt_eff,
            onvif_endpoint=body.onvif_endpoint,
            is_enabled=body.is_enabled,
            manufacturer=None,
            model=model_dev,
            extras=extras,
            monitor_hub_scope=body.monitor_hub_scope if body.monitor_hub_scope is not None else "local",
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
async def list_cameras(
    hub_scope: str | None = Query(
        None,
        description="«local» ou «online». Omitir = todas as câmaras.",
    ),
) -> list[CameraListItem]:
    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None
    hs = _parse_network_hub_scope_q(hub_scope)
    rows = await asyncio.to_thread(cam_mod.list_cameras, settings, hs)
    return [camera_row_to_list_item(r) for r in rows]


@app.get(
    "/cameras/discover/network",
    response_model=list[NetworkDiscoveredCamera],
    tags=["Câmeras"],
    summary="Procurar câmaras na rede (ONVIF + varredura IP)",
    description=(
        "1) Probe **SOAP** **WS-Discovery** UDP `239.255.255.250:3702` até `listen_seconds` (~ONVIF). "
        "2) Se `ip_scan=true`, varrimento **TCP** em portas comuns (554, 8554, 80…) na LAN /24 "
        "(pode apanhar **câmaras IP sem ONVIF**). Equipamentos com o mesmo IP em ambos ficam apenas na lista ONVIF."
    ),
    response_description="ONVIF primeiro; a seguir candidatos só IP (ordenados por relevância RTSP nas portas).",
)
async def discover_cameras_network(
    listen_seconds: float = Query(
        4.0,
        ge=1.0,
        le=15.0,
        description="Tempo máximo à escuta WS-Discovery (~4 s habitual).",
    ),
    ip_scan: bool = Query(True, description="Incluir varrimento TCP /24 sobre IPv4 locais."),
) -> list[NetworkDiscoveredCamera]:
    def _finalize_onvif(r: dict[str, Any]) -> dict[str, Any]:
        o = dict(r)
        o.setdefault("discovery_source", "onvif")
        if not isinstance(o.get("open_ports"), list):
            o["open_ports"] = []
        return o

    def _discovery_ip_key(d: dict[str, Any]) -> str:
        return str(d.get("ip_hint") or d.get("remote_ip") or "").strip()

    from app import ip_camera_scan as ipscan
    from app import onvif_ws_discovery as wd

    onvif_raw = await asyncio.to_thread(wd.probe_network, listen_seconds)

    finalized: list[dict[str, Any]] = [_finalize_onvif(x) for x in onvif_raw]
    merged: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    for row in finalized:
        merged.append(row)
        k = _discovery_ip_key(row)
        if k:
            seen_ips.add(k)

    if ip_scan:
        ip_scan_rows = await asyncio.to_thread(ipscan.probe_tcp_camera_hosts)
        for ir in ip_scan_rows:
            kk = _discovery_ip_key(ir)
            if kk and kk in seen_ips:
                continue
            if kk:
                seen_ips.add(kk)
            merged.append(ir)

    out: list[NetworkDiscoveredCamera] = []
    for item in merged:
        out.append(NetworkDiscoveredCamera.model_validate(item))
    return out


@app.post(
    "/cameras/probe-rtsp",
    response_model=RtspProbeResponse,
    tags=["Câmeras"],
    summary="Testar ligação RTSP antes de registar",
    description="Abre temporariamente a URL rtsp/rtmp/http para validar rede e credenciais (OpenCV).",
)
async def probe_rtsp_precheck(body: RtspProbeRequest) -> RtspProbeResponse:
    from app import cameras as cam_mod

    url = (body.rtsp_url or "").strip()
    if not url:
        return RtspProbeResponse(online=False, last_error="URL vazia")

    ok, err = await asyncio.to_thread(cam_mod.probe_rtsp, url, 5.0)
    return RtspProbeResponse(online=ok, last_error=err)


@app.post(
    "/cameras/onvif/media-profiles",
    response_model=list[OnvifMediaProfileRow],
    tags=["Câmeras"],
    summary="ONVIF: listar perfis e URIs RTSP",
    description=(
        "Contacta o serviço **Media ONVIF** (`GetProfiles`, `GetStreamUri`) "
        "e devolve as URLs RTSP associadas — útil ao escolher canal/stream no formulário "
        "**ONVIF avançado**. Requer o pacote `onvif-zeep` instalado na API."
    ),
)
async def onvif_media_profiles(body: OnvifMediaProfilesRequest) -> list[OnvifMediaProfileRow]:
    from app import cameras as cam_mod
    from app import onvif_streams as onv_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    try:
        raw = await asyncio.to_thread(
            onv_mod.list_media_stream_uris,
            body.ip_address.strip(),
            body.http_port,
            body.username or "",
            body.password or "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"ONVIF indisponível ou credenciais inválidas: {e}"[:380],
        ) from e

    return [OnvifMediaProfileRow.model_validate(x) for x in raw]


@app.get(
    "/cameras/{camera_id}",
    response_model=CameraListItem,
    tags=["Câmeras"],
    summary="Detalhe de uma câmara",
    description="Útil ao editar um registo registado anteriormente.",
)
async def get_camera_detail(
    camera_id: str = Path(
        ...,
        title="ID da câmara (UUID)",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
) -> CameraListItem:
    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    try:
        uuid.UUID(camera_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="camera_id inválido; use um UUID.") from e

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    row = await asyncio.to_thread(cam_mod.get_camera, settings, camera_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Câmara inexistente para este id.")
    return camera_row_to_list_item(row)


@app.put(
    "/cameras/{camera_id}",
    response_model=CameraListItem,
    tags=["Câmeras"],
    summary="Atualizar câmara",
)
async def update_camera_registration(
    body: CameraCreateRequest,
    camera_id: str = Path(
        ...,
        title="ID da câmara",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
) -> CameraListItem:
    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    try:
        uid = uuid.UUID(camera_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="camera_id inválido; use um UUID.") from e

    if body.http_port is not None and not (1 <= body.http_port <= 65535):
        raise HTTPException(
            status_code=400,
            detail="Porta inválida: use entre 1 e 65535, ou deixe o valor por defeito.",
        )

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    ip = (body.ip_address or "").strip()
    name = (body.name or "").strip() or f"Câmara {ip}"
    model_dev = ((body.device or "").strip() or None)[:64] if body.device else None
    extras = _extras_dict_from_camera_create(body)

    def _up() -> bool:
        dumped = body.model_dump(exclude_unset=True)
        rt_eff = cam_mod.compose_rtsp_url(
            ip,
            rtsp_url=body.rtsp_url,
            rtsp_tcp_port=body.rtsp_tcp_port,
            rtsp_path=body.rtsp_path,
            rtsp_username=body.rtsp_username,
            rtsp_password=body.rtsp_password,
        )
        mhs = dumped.get("monitor_hub_scope") if "monitor_hub_scope" in dumped else None
        return cam_mod.update_camera(
            settings,
            str(uid),
            name=name,
            ip_address=ip,
            http_port=body.http_port,
            rtsp_url=rt_eff,
            onvif_endpoint=body.onvif_endpoint,
            is_enabled=body.is_enabled,
            manufacturer=None,
            model=model_dev,
            extras=extras,
            monitor_hub_scope=mhs,
        )

    try:
        ok = await asyncio.to_thread(_up)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not ok:
        raise HTTPException(status_code=404, detail="Câmara inexistente para este id.")

    row = await asyncio.to_thread(cam_mod.get_camera, settings, str(uid))
    if row is None:
        raise HTTPException(status_code=404, detail="Câmara inexistente após atualização.")
    return camera_row_to_list_item(row)


@app.delete(
    "/cameras/{camera_id}",
    status_code=204,
    tags=["Câmeras"],
    summary="Eliminar câmara",
)
async def delete_camera_registration(
    camera_id: str = Path(
        ...,
        title="ID da câmara",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
) -> Response:
    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    try:
        uuid.UUID(camera_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="camera_id inválido; use um UUID.") from e

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    ok = await asyncio.to_thread(cam_mod.delete_camera, settings, camera_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Câmara inexistente para este id.")

    return Response(status_code=204)


def _parse_network_hub_scope_q(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip().lower()
    if s in ("local", "online"):
        return s
    raise HTTPException(
        status_code=400,
        detail="Parâmetro hub_scope inválido: use «local» ou «online».",
    )


@app.get(
    "/network-equipment",
    response_model=list[NetworkEquipmentMonitorItem],
    tags=["rede"],
    summary="Listar equipamentos monitorizados (LAN)",
    description=(
        "Resposta com estado **online** / **offline** / **sem_dados** (ainda não houve ping), "
        "duração do segmento atual e segundos acumulados em cada estado desde o registo."
    ),
)
async def list_network_equipment(
    hub_scope: str | None = Query(
        None,
        description="«local» (LAN) ou «online» (Internet). Omitir = todos os registos.",
    ),
) -> list[NetworkEquipmentMonitorItem]:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None
    hs = _parse_network_hub_scope_q(hub_scope)
    rows = await asyncio.to_thread(ne_mod.list_hosts, settings, hs)
    return [network_row_to_item(r) for r in rows]


@app.get(
    "/network-equipment/report/quedas.pdf",
    tags=["rede"],
    summary="Relatório PDF (quedas ICMP e câmaras)",
    response_class=Response,
)
async def network_equipment_quedas_pdf() -> Response:
    from app import cameras as cam_mod
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings
    from app.rede_quedas_pdf import build_quedas_pdf_bytes

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    def _load() -> tuple[list[NetworkEquipmentMonitorItem], list[CameraListItem]]:
        ne_rows = ne_mod.list_hosts(settings)
        icmp_items = [network_row_to_item(r) for r in ne_rows]
        cam_rows = cam_mod.list_cameras(settings)
        cam_items = [camera_row_to_list_item(r) for r in cam_rows]
        return icmp_items, cam_items

    try:
        icmp_items, cam_items = await asyncio.to_thread(_load)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    icmp_dicts = [
        {
            "nome": x.nome,
            "alvo": x.ip_ou_dns,
            "estado": x.estado,
            "quedas": x.quedas,
            "ambito": x.monitor_hub_scope,
        }
        for x in icmp_items
    ]
    cam_dicts = [
        {
            "nome": x.name,
            "ip": x.ip_address,
            "ativa": x.is_enabled,
            "quedas": x.quedas,
            "ambito": x.monitor_hub_scope,
        }
        for x in cam_items
    ]

    def _pdf() -> bytes:
        return build_quedas_pdf_bytes(icmp_rows=icmp_dicts, camera_rows=cam_dicts)

    try:
        body = await asyncio.to_thread(_pdf)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Falha ao gerar PDF (confirme dependência fpdf2 instalada): {e}",
        ) from e

    fn = datetime.now(timezone.utc).strftime("NeoVision-quedas-%Y%m%d-%H%M%SUTC.pdf")
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )


@app.get(
    "/network-equipment/report/quedas.csv",
    tags=["rede"],
    summary="Relatório de quedas em CSV",
)
async def network_equipment_quedas_csv() -> Response:
    from app import cameras as cam_mod
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings
    from app.rede_quedas_pdf import build_quedas_csv_text

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    def _load():
        ne_rows = ne_mod.list_hosts(settings)
        icmp_items = [network_row_to_item(r) for r in ne_rows]
        cam_rows = cam_mod.list_cameras(settings)
        cam_items = [camera_row_to_list_item(r) for r in cam_rows]
        return icmp_items, cam_items

    icmp_items, cam_items = await asyncio.to_thread(_load)

    icmp_dicts = [
        {"nome": x.nome, "alvo": x.ip_ou_dns, "estado": x.estado, "quedas": x.quedas, "ambito": x.monitor_hub_scope}
        for x in icmp_items
    ]
    cam_dicts = [
        {"nome": x.name, "ip": x.ip_address, "ativa": x.is_enabled, "quedas": x.quedas, "ambito": x.monitor_hub_scope}
        for x in cam_items
    ]

    txt = build_quedas_csv_text(icmp_rows=icmp_dicts, camera_rows=cam_dicts)
    fn = datetime.now(timezone.utc).strftime("NeoVision-quedas-%Y%m%d-%H%M%SUTC.csv")
    return Response(
        content=txt,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fn}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@app.post(
    "/network-equipment",
    response_model=NetworkEquipmentCreatedResponse,
    tags=["rede"],
    summary="Adicionar IP ou hostname a monitorizar",
)
async def create_network_equipment(body: NetworkEquipmentUpsert) -> NetworkEquipmentCreatedResponse:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    def _ins() -> str:
        ej = _merge_network_equipment_extras(None, body)
        mhs = body.monitor_hub_scope if body.monitor_hub_scope is not None else "local"
        return ne_mod.insert_host(
            settings,
            label=(body.nome or "").strip() or "Equipamento",
            ip_address=body.ip_address,
            poll_interval_seconds=body.poll_interval_seconds,
            is_enabled=body.is_enabled,
            icon_kind=body.icon_kind,
            extras_json=ej,
            monitor_hub_scope=mhs,
        )

    try:
        new_id = await asyncio.to_thread(_ins)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return NetworkEquipmentCreatedResponse(id=new_id)


@app.put(
    "/network-equipment/{host_id}",
    response_model=NetworkEquipmentMonitorItem,
    tags=["rede"],
    summary="Actualizar monitor de equipamento",
)
async def update_network_equipment(
    body: NetworkEquipmentUpsert,
    host_id: str = Path(
        ...,
        title="ID do registo",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
) -> NetworkEquipmentMonitorItem:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    try:
        uuid.UUID(host_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="host_id inválido; use um UUID.") from e

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    def _up() -> bool:
        dumped = body.model_dump(exclude_unset=True)
        extras_arg: Any = ne_mod.EXTRAS_JSON_UNCHANGED
        if any(
            k in dumped
            for k in (
                "url_painel_dvr",
                "usuario_painel_dvr",
                "senha_painel_dvr",
                "http_monitor_url",
            )
        ):
            cur = ne_mod.get_host(settings, host_id)
            extras_arg = _merge_network_equipment_extras(cur.extras_json if cur else None, body)
        mhs_arg: str | None = None
        if "monitor_hub_scope" in dumped:
            mhs_arg = dumped.get("monitor_hub_scope")
        return ne_mod.update_host(
            settings,
            host_id,
            label=(body.nome or "").strip() or "Equipamento",
            ip_address=body.ip_address,
            poll_interval_seconds=body.poll_interval_seconds,
            is_enabled=body.is_enabled,
            icon_kind=body.icon_kind,
            extras_json=extras_arg,
            monitor_hub_scope=mhs_arg,
        )

    try:
        ok = await asyncio.to_thread(_up)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not ok:
        raise HTTPException(status_code=404, detail="Registo não encontrado.")

    row = await asyncio.to_thread(ne_mod.get_host, settings, host_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado após atualização.")
    return network_row_to_item(row)


@app.delete(
    "/network-equipment/{host_id}",
    status_code=204,
    tags=["rede"],
    summary="Eliminar monitor de equipamento",
)
async def delete_network_equipment(
    host_id: str = Path(
        ...,
        title="ID do registo",
        examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"],
    ),
) -> Response:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    try:
        uuid.UUID(host_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="host_id inválido; use um UUID.") from e

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    ok = await asyncio.to_thread(ne_mod.delete_host, settings, host_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Registo não encontrado.")

    return Response(status_code=204)


@app.get(
    "/network-equipment/backup",
    response_model=NetworkEquipmentBackupPayload,
    tags=["rede"],
    summary="Exportar backup JSON dos equipamentos monitorizados",
    description=(
        "Devolve todos os IPs / nomes / intervalos / ícones e URLs do painel DVR para guardar num ficheiro. "
        "Num PC novo: importe o mesmo JSON (POST) para recriar a lista."
    ),
)
async def export_network_equipment_backup() -> NetworkEquipmentBackupPayload:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None
    rows = await asyncio.to_thread(ne_mod.backup_rows_for_export, settings)
    hosts = [NetworkEquipmentUpsert(**r) for r in rows]
    return NetworkEquipmentBackupPayload(
        exported_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        hosts=hosts,
    )


@app.post(
    "/network-equipment/backup",
    response_model=NetworkEquipmentBackupImportResult,
    tags=["rede"],
    summary="Importar backup JSON dos equipamentos",
    description=(
        "`replace_all=false` (padrão): actualiza registo com o mesmo **ip_address**; cria novos para IPs novos. "
        "`replace_all=true`: apaga todos os equipamentos antes (adequado a instalação limpa noutro PC)."
    ),
)
async def import_network_equipment_backup(
    body: NetworkEquipmentBackupImportBody,
) -> NetworkEquipmentBackupImportResult:
    from app import network_equipment as ne_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(ne_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    items = [h.model_dump(mode="python") for h in body.data.hosts]

    def _do() -> dict[str, int]:
        return ne_mod.import_backup_rows(settings, items, replace_all=body.replace_all)

    try:
        stats = await asyncio.to_thread(_do)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return NetworkEquipmentBackupImportResult(
        inserted=int(stats["inserted"]),
        updated=int(stats["updated"]),
        replaced_all=int(stats["replaced_all"]),
    )


@app.get(
    "/network/scan/ping",
    response_model=LanPingScanResponse,
    tags=["rede"],
    summary="Varrer IPs na LAN (ICMP, tipo Advanced IP Scanner)",
    description=(
        "Envia ping ICMP em paralelo sobre um **IPv4 /24 automático** (interfaces locais) "
        "ou um **CIDR** que você indique (ex. `192.168.88.0/24`). Limite típico: 1024 hosts. "
        "Não lista MAC (exige outros privilégios); opcionalmente resolve **nome de host** por PTR."
    ),
)
async def network_scan_ping(
    cidr: str = Query(
        "auto",
        description=(
            '`auto` = funde os /24 das IPv4 da máquina; ou informe IPv4+CIDR '
            "(ex. `192.168.1.0/24`, mínimo prefixo `/20`)."
        ),
    ),
    timeout_ms: int = Query(650, ge=250, le=3000),
    resolve_hostname: bool = Query(True, description="Consultar PTR para cada IP online (mais lento)."),
    max_workers: int = Query(48, ge=8, le=96, description="Concorrência de pings."),
) -> LanPingScanResponse:
    from app import lan_ping_scan as lps

    try:
        raw = await asyncio.to_thread(
            lps.scan_lan_ping,
            cidr=cidr,
            timeout_ms=timeout_ms,
            resolve_hostname=resolve_hostname,
            max_workers=max_workers,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return LanPingScanResponse(
        cidr_note=raw["cidr_note"],
        total_ips=int(raw["total_ips"]),
        alive_count=int(raw["alive_count"]),
        duration_sec=float(raw["duration_sec"]),
        results=[
            LanPingScanHostItem(
                ip=r["ip"],
                alive=r["alive"],
                latency_ms=r["latency_ms"],
                hostname=r["hostname"],
            )
            for r in raw["results"]
        ],
    )


@app.get(
    "/network/wifi/survey",
    response_model=WifiSurveyResponse,
    tags=["rede"],
    summary="Levantamento Wi‑Fi (canal, sinal, MAC)",
    description=(
        "Lista **BSSIDs** à vista no Windows via `netsh wlan show networks mode=Bssid` "
        "(intensidade, canal, banda, **MAC do AP**). Estima **Ubiquiti / provável UniFi** pelo prefixo OUI do MAC."
    ),
)
async def network_wifi_survey() -> WifiSurveyResponse:
    from app import wifi_survey as ws

    raw = await asyncio.to_thread(ws.survey_visible_networks)
    return WifiSurveyResponse(
        platform_supported=bool(raw["platform_supported"]),
        error=raw.get("error"),
        note=raw.get("note"),
        networks=[
            WifiSurveyBssidItem(
                ssid=str(n.get("ssid") or ""),
                bssid=str(n["bssid"]),
                signal_pct=n.get("signal_pct"),
                channel=n.get("channel"),
                radio_type=n.get("radio_type"),
                band=n.get("band"),
                authentication=n.get("authentication"),
                encryption=n.get("encryption"),
                vendor=n.get("vendor"),
                ap_hint=n.get("ap_hint"),
            )
            for n in raw.get("networks") or []
        ],
    )


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
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
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
            last_error="Defina `rtsp_url` no registo da câmara (painel ou desktop) para testar a ligação.",
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
    "/cameras/{camera_id}/stream.mjpeg",
    tags=["Câmeras"],
    summary="Stream MJPEG ao vivo (proxy RTSP via OpenCV)",
    description=(
        "Fluxo **multipart** `image/jpeg` para usar em `<img src=\"…\">` no painel **Tempo real**. "
        "Abre uma sessão de leitura RTSP **por pedido**; reduza o número de quadros ou qualidade se o CPU subir. "
        "Requer `rtsp_url` válido no registo e câmara activa."
    ),
    response_class=StreamingResponse,
)
async def camera_mjpeg_stream(
    camera_id: str = Path(..., description="UUID da câmara"),
    fps: float = Query(10.0, ge=2.0, le=25.0, description="Taxa máxima de fotogramas enviados."),
    quality: int = Query(72, ge=40, le=95, description="Qualidade JPEG (40–95)."),
    width: int = Query(
        1024,
        ge=0,
        le=1920,
        description="Largura máxima em pixels (proporção mantida; 0 = sem redimensionar).",
    ),
) -> StreamingResponse:
    try:
        uid = uuid.UUID(camera_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="camera_id inválido; use um UUID (ex.: 3fa85f64-...)."
        ) from e

    from app import cameras as cam_mod
    from app.db_settings import DatabaseSettings

    settings = DatabaseSettings.from_environ()
    if err := await asyncio.to_thread(cam_mod.db_ping_error, settings):
        raise _http_db503(err) from None

    row = await asyncio.to_thread(cam_mod.get_camera, settings, str(uid))
    if row is None:
        raise HTTPException(status_code=404, detail="Câmara inexistente para este id.")
    if not row.is_enabled:
        raise HTTPException(status_code=403, detail="Câmara desativada.")
    if not (row.rtsp_url or "").strip():
        raise HTTPException(status_code=400, detail="Defina rtsp_url no registo para transmitir vídeo.")

    max_w = int(width) if int(width) > 0 else 0

    def _frames():
        yield from cam_mod.iter_mjpeg_multipart_from_rtsp(
            row.rtsp_url or "",
            jpeg_quality=int(quality),
            max_fps=float(fps),
            max_width=max_w,
        )

    return StreamingResponse(
        iterate_in_threadpool(_frames()),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
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
