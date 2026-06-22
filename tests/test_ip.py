import ipaddress

import pytest

from pyvpn.errors import ProtocolError
from pyvpn.ip import inspect_ipv4


def ipv4_packet(src: str, dst: str, payload: bytes = b"abc") -> bytes:
    total = 20 + len(payload)
    header = bytearray(20)
    header[0] = 0x45
    header[2:4] = total.to_bytes(2, "big")
    header[8] = 64
    header[9] = 6
    header[12:16] = ipaddress.IPv4Address(src).packed
    header[16:20] = ipaddress.IPv4Address(dst).packed
    return bytes(header) + payload


def test_inspect_ipv4_packet() -> None:
    info = inspect_ipv4(ipv4_packet("10.8.0.2", "1.1.1.1"))
    assert str(info.source) == "10.8.0.2"
    assert str(info.destination) == "1.1.1.1"
    assert info.protocol == 6
    assert info.total_length == 23


def test_rejects_non_ipv4() -> None:
    with pytest.raises(ProtocolError):
        inspect_ipv4(b"\x60" + b"\x00" * 39)
