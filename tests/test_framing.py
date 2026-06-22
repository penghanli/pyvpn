import pytest

from pyvpn.errors import ProtocolError
from pyvpn.framing import decode_frame_bytes, encode_frame


def test_json_frame_round_trip() -> None:
    message = {"type": "hello", "version": 1, "capabilities": ["ipv4"]}
    assert decode_frame_bytes(encode_frame(message)) == message


def test_rejects_truncated_frame() -> None:
    with pytest.raises(ProtocolError):
        decode_frame_bytes(b"\x00\x00\x00\x08{}")
