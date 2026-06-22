"""Windows integration boundary.

The encrypted tunnel protocol is shared with Windows, but a production Windows
client needs a Wintun adapter binding. Keeping this as an explicit boundary is
better than silently falling back to an application proxy and calling it a VPN.
"""

from __future__ import annotations

WINTUN_REQUIRED_MESSAGE = (
    "Windows system-wide VPN support requires a Wintun ctypes binding and "
    "adapter lifecycle management. The current CLI refuses to run on Windows "
    "until that binding is implemented."
)

__all__ = ["WINTUN_REQUIRED_MESSAGE"]
