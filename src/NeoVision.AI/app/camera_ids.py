"""Conversão UUID <-> 16 bytes no formato de `System.Guid` (.NET) usada na tabela `cameras`."""

from __future__ import annotations

import struct
import uuid


def dotnet_bytes_to_uuid(b: bytes) -> uuid.UUID:
    if len(b) != 16:
        msg = f"id com {len(b)} bytes; esperados 16"
        raise ValueError(msg)
    rfc = struct.pack(">IHH", *struct.unpack("<IHH", b[0:8])) + b[8:16]
    return uuid.UUID(bytes=rfc)


def uuid_to_dotnet_bytes(u: uuid.UUID) -> bytes:
    b = u.bytes
    return struct.pack("<IHH", *struct.unpack(">IHH", b[0:8])) + b[8:16]
