# pyvpn Windows desktop client

`pyvpn.exe` is a single-file Windows 10/11 x64 client containing Python,
pyvpn, its Python dependencies, and the official AMD64 Wintun binary. The
target computer does not need Python or an internet connection.

## Use

1. Double-click `pyvpn.exe` and approve the UAC administrator prompt.
2. Select Add server and enter an ID, host, control port, shared token, and
   the server certificate SHA-256 fingerprint.
3. Select the server, choose Switch to this server, and then Connect.
4. Test all measures TCP control-port connection latency. It is not a
   bandwidth measurement.

Connected means an authenticated UDP response was received from the server.
The app first tries to repair routes after a Windows network change and keeps retrying if needed, showing
"Reconnecting" while it retries, and tolerates a brief failed route check. A pending
connection can be cancelled.
This version writes decrypted UDP data to Wintun in order and in batches, and
reconnects when Wintun writes remain blocked.

Before connecting, the GUI installs persistent Windows Firewall block rules on wired and
wireless interfaces. Only the selected server IPv4 is exempted; other public IPv4,
public IPv6, and physical-interface TCP/UDP DNS on port 53 are blocked. LAN and DHCP
remain available for network handover. The rules stay active through retries and a worker
crash; they are removed on an intentional disconnect or with the Release protection button.
Profiles containing `bypass_ips` cannot connect in this mode. There is no automatic server
switching, so the VPN exit IP remains the same if reconnecting to the same server.
Latency testing is disabled while the guard is active and the VPN is disconnected;
after connection, latency tests run through the active VPN.

If the EXE cannot open, recover internet access in an elevated PowerShell:

```powershell
Get-NetFirewallRule -PolicyStore PersistentStore -Name 'pyvpn-public-guard-*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
```

Firewall policy changes, non-wired/non-wireless uplinks, and local-network traffic are
outside this guard's scope. Test link loss and IPv6 on each target machine before relying
on it. Spoofing the client's source IP cannot make an unreachable server reachable.

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
Keep `pyvpn-data` when replacing the EXE to retain profiles and the client ID.

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
