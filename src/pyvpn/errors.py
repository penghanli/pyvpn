"""Project-specific exceptions."""


class PyVpnError(Exception):
    """Base error for pyvpn."""


class ProtocolError(PyVpnError):
    """Raised when a peer sends invalid protocol data."""


class PlatformError(PyVpnError):
    """Raised when the requested platform operation is unsupported or unsafe."""


class AuthenticationError(PyVpnError):
    """Raised when authentication or certificate pinning fails."""
