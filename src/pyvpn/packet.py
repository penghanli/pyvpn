"""Encrypted UDP data packet codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import (
    DATA_VERSION,
    MAGIC,
    PACKET_TYPE_DATA,
    PACKET_TYPE_KEEPALIVE,
)
from .crypto import TunnelCipher
from .errors import ProtocolError

_HEADER = struct.Struct("!4sBBQQ")
HEADER_SIZE = _HEADER.size
VALID_PACKET_TYPES = {PACKET_TYPE_DATA, PACKET_TYPE_KEEPALIVE}


@dataclass(frozen=True)
class PacketHeader:
    version: int
    packet_type: int
    session_id: int
    seq: int

    def encode(self) -> bytes:
        if self.packet_type not in VALID_PACKET_TYPES:
            raise ProtocolError("invalid packet type")
        return _HEADER.pack(MAGIC, self.version, self.packet_type, self.session_id, self.seq)


def parse_header(data: bytes) -> PacketHeader:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("truncated tunnel packet")
    magic, version, packet_type, session_id, seq = _HEADER.unpack(data[:HEADER_SIZE])
    if magic != MAGIC:
        raise ProtocolError("invalid tunnel packet magic")
    if version != DATA_VERSION:
        raise ProtocolError("unsupported tunnel packet version")
    if packet_type not in VALID_PACKET_TYPES:
        raise ProtocolError("invalid tunnel packet type")
    return PacketHeader(version=version, packet_type=packet_type, session_id=session_id, seq=seq)


def seal_packet(
    packet_type: int,
    session_id: int,
    seq: int,
    plaintext: bytes,
    cipher: TunnelCipher,
) -> bytes:
    header = PacketHeader(DATA_VERSION, packet_type, session_id, seq).encode()
    return header + cipher.encrypt(seq, plaintext, header)


def open_packet(data: bytes, cipher: TunnelCipher) -> tuple[PacketHeader, bytes]:
    header = parse_header(data)
    header_bytes = data[:HEADER_SIZE]
    ciphertext = data[HEADER_SIZE:]
    return header, cipher.decrypt(header.seq, ciphertext, header_bytes)
