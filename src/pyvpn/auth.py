"""Authentication helpers."""

from __future__ import annotations

import hashlib
import hmac


def token_matches(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8"))


def certificate_fingerprint(cert_der: bytes) -> str:
    return "sha256:" + hashlib.sha256(cert_der).hexdigest()


def normalize_fingerprint(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned.startswith("sha256:"):
        cleaned = cleaned.removeprefix("sha256:")
    cleaned = cleaned.replace(":", "").replace(" ", "")
    return "sha256:" + cleaned
