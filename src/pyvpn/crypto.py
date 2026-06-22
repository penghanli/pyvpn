"""Tunnel encryption helpers."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from .constants import AEAD_NAME
from .errors import ProtocolError

KEY_BYTES = 32
SALT_BYTES = 4


def b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ProtocolError("invalid base64 value") from exc


@dataclass(frozen=True)
class DirectionKey:
    key: bytes
    salt: bytes

    def to_json(self) -> dict[str, str]:
        return {"key": b64encode(self.key), "salt": b64encode(self.salt)}

    @classmethod
    def from_json(cls, value: dict[str, str]) -> "DirectionKey":
        key = b64decode(value["key"])
        salt = b64decode(value["salt"])
        if len(key) != KEY_BYTES:
            raise ProtocolError("invalid tunnel key length")
        if len(salt) != SALT_BYTES:
            raise ProtocolError("invalid tunnel salt length")
        return cls(key=key, salt=salt)


@dataclass(frozen=True)
class SessionKeys:
    c2s: DirectionKey
    s2c: DirectionKey

    def to_json(self) -> dict[str, object]:
        return {"aead": AEAD_NAME, "c2s": self.c2s.to_json(), "s2c": self.s2c.to_json()}

    @classmethod
    def from_json(cls, value: dict[str, object]) -> "SessionKeys":
        if value.get("aead") != AEAD_NAME:
            raise ProtocolError("unsupported tunnel AEAD")
        c2s = value.get("c2s")
        s2c = value.get("s2c")
        if not isinstance(c2s, dict) or not isinstance(s2c, dict):
            raise ProtocolError("invalid session key object")
        return cls(c2s=DirectionKey.from_json(c2s), s2c=DirectionKey.from_json(s2c))


def new_session_keys() -> SessionKeys:
    return SessionKeys(
        c2s=DirectionKey(os.urandom(KEY_BYTES), os.urandom(SALT_BYTES)),
        s2c=DirectionKey(os.urandom(KEY_BYTES), os.urandom(SALT_BYTES)),
    )


class TunnelCipher:
    def __init__(self, direction_key: DirectionKey):
        self._key = direction_key
        self._aead = ChaCha20Poly1305(direction_key.key)

    def nonce(self, seq: int) -> bytes:
        if seq <= 0 or seq >= 2**64:
            raise ProtocolError("invalid packet sequence number")
        return self._key.salt + seq.to_bytes(8, "big")

    def encrypt(self, seq: int, plaintext: bytes, aad: bytes) -> bytes:
        return self._aead.encrypt(self.nonce(seq), plaintext, aad)

    def decrypt(self, seq: int, ciphertext: bytes, aad: bytes) -> bytes:
        try:
            return self._aead.decrypt(self.nonce(seq), ciphertext, aad)
        except InvalidTag as exc:
            raise ProtocolError("invalid encrypted tunnel packet") from exc
