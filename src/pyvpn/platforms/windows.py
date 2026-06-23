"""Windows integration notes."""

from __future__ import annotations

WINTUN_REQUIRED_MESSAGE = (
    "Windows system-wide VPN support requires wintun.dll beside the Python "
    "entry point. Run scripts/windows/install-client.ps1 from an elevated "
    "PowerShell window."
)

__all__ = ["WINTUN_REQUIRED_MESSAGE"]
