# macOS NetworkExtension client

macOS production packaging should use a signed `NEPacketTunnelProvider`
extension. For direct CLI testing, the Python client now has an experimental
sudo-based `utun` path; see `docs/macos-client.md`.

This folder contains the v1 integration skeleton. It is intentionally separate
from the Python CLI packaging:

1. Create an Xcode app target and a Packet Tunnel extension target.
2. Add `PacketTunnelProvider.swift` to the extension target.
3. Pass provider configuration keys:
   - `serverHost`
   - `controlPort`
   - `token`
   - `certFingerprint`
4. Implement `PyVpnControlClient` and `PyVpnUdpTunnel` using the same protocol
   defined in `src/pyvpn/framing.py` and `src/pyvpn/packet.py`.

The current Swift file installs the packet tunnel network settings and shows the
exact hook where encrypted UDP forwarding must be connected to `packetFlow`.
