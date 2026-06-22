"""Self-signed certificate helper for pyvpn servers."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .auth import certificate_fingerprint


def generate_self_signed(common_name: str, days: int) -> tuple[bytes, bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    alt_names: list[x509.GeneralName] = [x509.DNSName(common_name)]
    try:
        alt_names.append(x509.IPAddress(ipaddress.ip_address(common_name)))
    except ValueError:
        pass

    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    fingerprint = certificate_fingerprint(cert.public_bytes(serialization.Encoding.DER))
    return cert_pem, key_pem, fingerprint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a pyvpn self-signed certificate")
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--common-name", required=True)
    parser.add_argument("--days", type=int, default=3650)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cert_pem, key_pem, fingerprint = generate_self_signed(args.common_name, args.days)
    Path(args.cert).write_bytes(cert_pem)
    key_path = Path(args.key)
    key_path.write_bytes(key_pem)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    print(f"certificate fingerprint: {fingerprint}")


if __name__ == "__main__":
    main()
