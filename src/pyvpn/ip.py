"""Small IPv4 packet inspection helpers."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .errors import ProtocolError


@dataclass(frozen=True)
class IPv4PacketInfo:
    source: ipaddress.IPv4Address
    destination: ipaddress.IPv4Address
    protocol: int
    total_length: int


def inspect_ipv4(packet: bytes) -> IPv4PacketInfo:
    if len(packet) < 20:
        raise ProtocolError("truncated IPv4 packet")
    version = packet[0] >> 4
    ihl = packet[0] & 0x0F
    if version != 4:
        raise ProtocolError("not an IPv4 packet")
    header_len = ihl * 4
    if ihl < 5 or len(packet) < header_len:
        raise ProtocolError("invalid IPv4 header length")
    total_length = int.from_bytes(packet[2:4], "big")
    if total_length < header_len or total_length > len(packet):
        raise ProtocolError("invalid IPv4 total length")
    return IPv4PacketInfo(
        source=ipaddress.IPv4Address(packet[12:16]),
        destination=ipaddress.IPv4Address(packet[16:20]),
        protocol=packet[9],
        total_length=total_length,
    )
