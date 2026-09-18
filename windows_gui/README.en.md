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

Profiles and logs normally stay in `pyvpn-data` beside the executable. When
the executable is placed in the root of an installed Windows offline package,
it reuses `pyvpn-client\config\servers.json`, so the command-line scripts and
GUI share the same servers. `PYVPN_GUI_DATA_DIR` can override the data
directory and `PYVPN_PROFILE_FILE` can select an existing profile file.

The app requests a graceful disconnect before closing. Tokens are never shown
in the server list, but they are stored in plaintext in the local
`servers.json`; do not share the data directory or profile file. The app tries
to restrict a newly created data directory to Windows Administrators and
SYSTEM. Every connection validates the configured certificate fingerprint.

## Build

On Windows x64 with Python 3.12:

```powershell
python -m pip install -r offline_release\build-requirements.txt
python windows_gui\build.py
```

The output in `windows_gui\dist` contains `pyvpn.exe`, its SHA-256 file, and a
versioned ZIP. The build is not Authenticode-signed; sign it with your
organization's code-signing certificate before customer distribution.
