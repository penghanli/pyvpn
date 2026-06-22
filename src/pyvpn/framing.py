"""Length-prefixed JSON control frames."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from typing import Any

from .constants import MAX_FRAME_BYTES
from .errors import ProtocolError

_LEN = struct.Struct("!I")


def encode_frame(message: Mapping[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError(f"control frame too large: {len(payload)} bytes")
    return _LEN.pack(len(payload)) + payload


def decode_payload(payload: bytes) -> dict[str, Any]:
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON control frame") from exc
    if not isinstance(message, dict):
        raise ProtocolError("control frame must be a JSON object")
    return message


def decode_frame_bytes(data: bytes) -> dict[str, Any]:
    if len(data) < _LEN.size:
        raise ProtocolError("truncated control frame header")
    (length,) = _LEN.unpack(data[: _LEN.size])
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"control frame too large: {length} bytes")
    payload = data[_LEN.size :]
    if len(payload) != length:
        raise ProtocolError("truncated control frame payload")
    return decode_payload(payload)


async def read_frame(reader) -> dict[str, Any]:
    header = await reader.readexactly(_LEN.size)
    (length,) = _LEN.unpack(header)
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"control frame too large: {length} bytes")
    payload = await reader.readexactly(length)
    return decode_payload(payload)


async def write_frame(writer, message: Mapping[str, Any]) -> None:
    writer.write(encode_frame(message))
    await writer.drain()
