# pyvpn Windows desktop client

`pyvpn.exe` is a single-file Windows 10/11 x64 client containing Python,
pyvpn, its Python dependencies, and the official AMD64 Wintun binary. The
target computer does not need Python or an internet connection.

## Use

1. Double-click `pyvpn.exe` and approve the UAC administrator prompt.
2. Select Add server and enter an ID, host, control port, shared token, and
   the server certificate SHA-256 fingerprint. New profiles default to a
   `LocalNetwork` adapter name, which can be edited per profile.
3. Select the server, choose Switch to this server, and then Connect.
4. Test all measures TCP control-port connection latency. It is not a
   bandwidth measurement.

Connected means an authenticated UDP response was received from the server.
The app first tries to repair routes after a Windows network change and keeps retrying if needed, showing
"Reconnecting" while it retries, and tolerates a brief failed route check. A pending
connection can be cancelled.
This version writes decrypted UDP data to Wintun in order and in batches, and
reconnects when Wintun writes remain blocked.

Before connecting, the GUI installs persistent Windows Firewall rules across all
interfaces. Except for the VPN virtual source address, only the selected server IPv4
is exempted; other public IPv4 and IPv6 destinations, including public DNS, are blocked.
LAN DNS and DHCP remain available for network handover and hostname refresh. The rules stay active through retries and a worker
crash; they are removed on an intentional disconnect or with the Release protection button.
Profiles containing `bypass_ips` cannot connect in this mode. There is no automatic server
switching, so the VPN exit IP remains the same if reconnecting to the same server.
Latency testing is disabled while the guard is active and the VPN is disconnected;
after connection, latency tests run through the active VPN.

If the EXE cannot open, recover internet access in an elevated PowerShell:

```powershell
Get-NetFirewallRule -PolicyStore PersistentStore -Name 'pyvpn-public-guard-*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
```

Firewall policy changes, other proxies or virtual adapters, and local-network traffic
still require testing on each target machine. Test link loss, network handover, and IPv6
before relying on the guard. Spoofing the client's source IP cannot make an unreachable server reachable.
The adapter name is only a local Windows label; it does not hide the Wintun driver,
process, or traffic pattern. Existing profiles retain their adapter names. Disconnect,
edit the profile's adapter name, and reconnect to rename it; the previous virtual adapter
is not removed automatically. A hostname is resolved again on reconnect. If the guarded
machine only has public DNS, hostname updates can fail; use reachable LAN DNS or a server IPv4.

Profiles, the client ID, and logs normally stay in `pyvpn-data` beside the executable. When
the executable is placed in the root of an installed Windows offline package,
it reuses `pyvpn-client\config\servers.json`, so the command-line scripts and
GUI share the same servers. `PYVPN_GUI_DATA_DIR` can override the data
directory and `PYVPN_PROFILE_FILE` can select an existing profile file.

The app requests a graceful disconnect before closing. Tokens are never shown
in the server list, but they are stored in plaintext in the local
`servers.json`; do not share the data directory or profile file. The app tries
to restrict a newly created data directory to Windows Administrators and
SYSTEM. Every connection validates the configured certificate fingerprint.
Keep `pyvpn-data` when replacing the EXE to retain profiles. The client ID stays stable
on one machine, but a copied data directory derives a different ID on another Windows
machine so the two installations do not replace each other's server sessions.

Use View logs to open the data directory. `client.log` records connection attempts;
`client.err.log` records retry reasons and failures. Logs append across sessions and
rotate to a `.1` backup on the next connection after reaching 5 MiB. Note the time
of a failure and review logs for server addresses or local network details before
sharing them. Never share `servers.json` or a token.

Test all checks only the TCP control port, not the UDP data path. If an
application reports `ECONNRESET`, also check whether that application has its
own HTTP/HTTPS proxy configured.

## Build

On Windows x64 with Python 3.12:

```powershell
python -m pip install -r offline_release\build-requirements.txt
python windows_gui\build.py
```

The output in `windows_gui\dist` contains `pyvpn.exe`, its SHA-256 file, and a
versioned ZIP. The build is not Authenticode-signed; sign it with your
organization's code-signing certificate before customer distribution.
