#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_ID="default"
SERVER_ID_SET="0"
SERVER_HOST=""
TOKEN=""
CERT_FINGERPRINT=""
CONTROL_PORT="8443"
INSTALL_DIR=""
CONFIG_DIR=""
TUN_NAME="pyvpn0"
MTU="1280"
NO_DNS="0"
BYPASS_IPS=()
PROFILE_INPUT_PROVIDED="0"

usage() {
  cat <<'EOF'
Usage:
  sudo ./install-client.sh [options]

Options:
  --server-id ID
  --server-host HOST
  --token TOKEN
  --cert-fingerprint FP
  --control-port PORT
  --bypass-ip IP
  --install-dir DIR
  --config-dir DIR
  --tun NAME
  --mtu MTU
  --no-dns
EOF
}

trim_outer_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-id) SERVER_ID="${2:-}"; SERVER_ID_SET="1"; shift 2 ;;
    --server-host) SERVER_HOST="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --token) TOKEN="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --cert-fingerprint) CERT_FINGERPRINT="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --control-port) CONTROL_PORT="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --bypass-ip) BYPASS_IPS+=("${2:-}"); PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:-}"; shift 2 ;;
    --tun) TUN_NAME="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --mtu) MTU="${2:-}"; PROFILE_INPUT_PROVIDED="1"; shift 2 ;;
    --no-dns) NO_DNS="1"; PROFILE_INPUT_PROVIDED="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this installer with sudo/root." >&2
  exit 1
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This offline package supports Linux only." >&2
  exit 1
fi

PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
METADATA="$PACKAGE_ROOT/PACKAGE-METADATA"
MANIFEST="$PACKAGE_ROOT/SHA256SUMS"
metadata_value() {
  sed -n "s/^$1=//p" "$METADATA" | tail -n 1
}

if [[ ! -f "$METADATA" || ! -f "$MANIFEST" ]]; then
  echo "PACKAGE-METADATA or SHA256SUMS is missing. Extract the complete package." >&2
  exit 1
fi
for command_name in sha256sum ip nohup awk sed; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required system command is missing: $command_name" >&2
    exit 1
  fi
done
(cd "$PACKAGE_ROOT" && sha256sum --check --quiet SHA256SUMS)

PACKAGE_PLATFORM="$(metadata_value PLATFORM)"
PACKAGE_ARCH="$(metadata_value ARCH)"
PACKAGE_ROLE="$(metadata_value ROLE)"
if [[ "$PACKAGE_PLATFORM" != "linux" || "$PACKAGE_ROLE" != "client" ]]; then
  echo "This is not a Linux client package." >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64|amd64) ACTUAL_ARCH="x86_64" ;;
  aarch64|arm64) ACTUAL_ARCH="arm64" ;;
  *) echo "Unsupported Linux architecture: $(uname -m)" >&2; exit 1 ;;
esac
if [[ "$ACTUAL_ARCH" != "$PACKAGE_ARCH" ]]; then
  echo "Wrong package architecture: package=$PACKAGE_ARCH machine=$ACTUAL_ARCH" >&2
  exit 1
fi
if [[ ! -e /dev/net/tun ]]; then
  echo "/dev/net/tun is missing. Enable the Linux TUN driver before installation." >&2
  exit 1
fi

PAYLOAD_DIR="$PACKAGE_ROOT/payload/pyvpn-client"
PAYLOAD_EXE="$PAYLOAD_DIR/pyvpn-client"
if [[ ! -x "$PAYLOAD_EXE" ]]; then
  echo "Bundled pyvpn-client is missing or not executable." >&2
  exit 1
fi
"$PAYLOAD_EXE" --help >/dev/null

if [[ -z "$INSTALL_DIR" ]]; then INSTALL_DIR="$PACKAGE_ROOT/pyvpn-client"; fi
if [[ -z "$CONFIG_DIR" ]]; then CONFIG_DIR="$INSTALL_DIR/config"; fi
for path_value in "$INSTALL_DIR" "$CONFIG_DIR"; do
  case "$path_value" in
    /*) ;;
    *) echo "Installation paths must be absolute." >&2; exit 2 ;;
  esac
done
if [[ "$INSTALL_DIR" == "$PACKAGE_ROOT" || "$INSTALL_DIR" == "$PAYLOAD_DIR" ||
      "$INSTALL_DIR" == "$PAYLOAD_DIR/"* ]]; then
  echo "--install-dir must be a new directory outside the packaged payload." >&2
  exit 2
fi

PAYLOAD_KB="$(du -sk "$PAYLOAD_DIR" | awk '{print $1}')"
AVAILABLE_KB="$(df -Pk "$PACKAGE_ROOT" | awk 'NR==2 {print $4}')"
REQUIRED_KB="$((PAYLOAD_KB * 3 + 51200))"
if [[ "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]]; then
  echo "Not enough free disk space. Required: ${REQUIRED_KB} KiB." >&2
  exit 1
fi

PROFILES_PATH="$CONFIG_DIR/servers.json"
WRITE_PROFILE="0"
SELECT_EXISTING="0"
if [[ ! -f "$PROFILES_PATH" || "$PROFILE_INPUT_PROVIDED" == "1" ]]; then
  WRITE_PROFILE="1"
elif [[ "$SERVER_ID_SET" == "1" ]]; then
  SELECT_EXISTING="1"
fi

if [[ "$WRITE_PROFILE" == "1" ]]; then
  if [[ -z "$SERVER_HOST" ]]; then read -r -p "Server host or IP: " SERVER_HOST; fi
  if [[ -z "$TOKEN" ]]; then
    read -r -s -p "Shared token: " TOKEN
    echo
  fi
  TOKEN="$(trim_outer_whitespace "$TOKEN")"
  if [[ -z "$CERT_FINGERPRINT" ]]; then
    read -r -p "Certificate fingerprint (sha256:...): " CERT_FINGERPRINT
  fi
  if [[ ! "$SERVER_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "server_id contains unsupported characters: $SERVER_ID" >&2
    exit 2
  fi
  if [[ -z "$SERVER_HOST" || -z "$TOKEN" || -z "$CERT_FINGERPRINT" ]]; then
    echo "Server host, token, and certificate fingerprint are required." >&2
    exit 2
  fi
  if [[ ! "$CERT_FINGERPRINT" =~ ^sha256:[0-9a-fA-F]{64}$ ]]; then
    echo "Certificate fingerprint must be sha256 followed by 64 hexadecimal characters." >&2
    exit 2
  fi
  if [[ ! "$CONTROL_PORT" =~ ^[0-9]+$ || "$CONTROL_PORT" -lt 1 || "$CONTROL_PORT" -gt 65535 ]]; then
    echo "Control port must be from 1 to 65535." >&2
    exit 2
  fi
  if [[ ! "$MTU" =~ ^[0-9]+$ || "$MTU" -lt 576 || "$MTU" -gt 9000 ]]; then
    echo "MTU must be from 576 to 9000." >&2
    exit 2
  fi
fi

RUNTIME="$INSTALL_DIR/runtime"
RUNTIME_NEW="$INSTALL_DIR/runtime.new"
RUNTIME_PREVIOUS="$INSTALL_DIR/runtime.previous"
START_SCRIPT="$INSTALL_DIR/pyvpn-client-start"
UP_SCRIPT="$INSTALL_DIR/pyvpn-client-up"
DOWN_SCRIPT="$INSTALL_DIR/pyvpn-client-down"
STATUS_SCRIPT="$INSTALL_DIR/pyvpn-client-status"
SERVERS_SCRIPT="$INSTALL_DIR/pyvpn-client-servers"
SWITCH_SCRIPT="$INSTALL_DIR/pyvpn-client-switch"
PID_FILE="$CONFIG_DIR/client.pid"
STOP_FILE="$CONFIG_DIR/client.stop"
LOG_FILE="$CONFIG_DIR/client.log"
ERR_FILE="$CONFIG_DIR/client.err.log"

WAS_ACTIVE="0"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" >/dev/null 2>&1; then WAS_ACTIVE="1"; fi
fi

echo "Environment check passed: Linux architecture, root, package, TUN, commands, and disk space."
BACKUP_DIR="$(mktemp -d /tmp/pyvpn-offline-client.XXXXXX)"
BACKUP_PATHS=(
  "$PROFILES_PATH"
  "$START_SCRIPT"
  "$UP_SCRIPT"
  "$DOWN_SCRIPT"
  "$STATUS_SCRIPT"
  "$SERVERS_SCRIPT"
  "$SWITCH_SCRIPT"
)
for index in "${!BACKUP_PATHS[@]}"; do
  path="${BACKUP_PATHS[$index]}"
  if [[ -f "$path" ]]; then
    cp -a "$path" "$BACKUP_DIR/$index"
    echo 1 > "$BACKUP_DIR/$index.exists"
  else
    echo 0 > "$BACKUP_DIR/$index.exists"
  fi
done

OLD_RUNTIME_MOVED="0"
NEW_RUNTIME_INSTALLED="0"
rollback() {
  local exit_code=$?
  trap - ERR
  set +e
  for index in "${!BACKUP_PATHS[@]}"; do
    path="${BACKUP_PATHS[$index]}"
    if [[ "$(cat "$BACKUP_DIR/$index.exists")" == "1" ]]; then
      mkdir -p "$(dirname "$path")"
      cp -a "$BACKUP_DIR/$index" "$path"
    else
      rm -f "$path"
    fi
  done
  rm -rf "$RUNTIME_NEW"
  if [[ "$NEW_RUNTIME_INSTALLED" == "1" ]]; then rm -rf "$RUNTIME"; fi
  if [[ "$OLD_RUNTIME_MOVED" == "1" && -d "$RUNTIME_PREVIOUS" ]]; then
    mv "$RUNTIME_PREVIOUS" "$RUNTIME"
  fi
  if [[ "$WAS_ACTIVE" == "1" && -x "$UP_SCRIPT" ]]; then "$UP_SCRIPT" >/dev/null 2>&1; fi
  rm -rf "$BACKUP_DIR"
  echo "Offline client installation failed; the previous local installation was restored." >&2
  exit "$exit_code"
}
trap rollback ERR

if [[ -x "$DOWN_SCRIPT" ]]; then "$DOWN_SCRIPT" >/dev/null 2>&1 || true; fi
if [[ "$WAS_ACTIVE" == "1" ]] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
  echo "The existing local pyvpn client did not stop." >&2
  false
fi

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
chmod 700 "$INSTALL_DIR" "$CONFIG_DIR"
rm -rf "$RUNTIME_NEW"
cp -a "$PAYLOAD_DIR" "$RUNTIME_NEW"
chown -R root:root "$RUNTIME_NEW"
chmod -R go-w "$RUNTIME_NEW"
"$RUNTIME_NEW/pyvpn-client" --help >/dev/null
rm -rf "$RUNTIME_PREVIOUS"
if [[ -d "$RUNTIME" ]]; then
  mv "$RUNTIME" "$RUNTIME_PREVIOUS"
  OLD_RUNTIME_MOVED="1"
fi
mv "$RUNTIME_NEW" "$RUNTIME"
NEW_RUNTIME_INSTALLED="1"
RUNTIME_EXE="$RUNTIME/pyvpn-client"

if [[ "$WRITE_PROFILE" == "1" ]]; then
  PROFILE_ARGS=(
    servers --file "$PROFILES_PATH" add "$SERVER_ID"
    --server-host "$SERVER_HOST"
    --control-port "$CONTROL_PORT"
    --cert-fingerprint "$CERT_FINGERPRINT"
    --tun "$TUN_NAME"
    --mtu "$MTU"
    --replace --use
  )
  for bypass_ip in "${BYPASS_IPS[@]-}"; do
    [[ -z "$bypass_ip" ]] || PROFILE_ARGS+=(--bypass-ip "$bypass_ip")
  done
  if [[ "$NO_DNS" == "1" ]]; then PROFILE_ARGS+=(--no-dns); fi
  env PYVPN_TOKEN="$TOKEN" "$RUNTIME_EXE" "${PROFILE_ARGS[@]}" >/dev/null
else
  "$RUNTIME_EXE" servers --file "$PROFILES_PATH" list --no-probe >/dev/null
  if [[ "$SELECT_EXISTING" == "1" ]]; then
    "$RUNTIME_EXE" servers --file "$PROFILES_PATH" use "$SERVER_ID" >/dev/null
  fi
fi
chown root:root "$PROFILES_PATH"
chmod 600 "$PROFILES_PATH"

RUNTIME_EXE_Q="$(printf '%q' "$RUNTIME_EXE")"
PROFILES_PATH_Q="$(printf '%q' "$PROFILES_PATH")"
PID_FILE_Q="$(printf '%q' "$PID_FILE")"
STOP_FILE_Q="$(printf '%q' "$STOP_FILE")"
LOG_FILE_Q="$(printf '%q' "$LOG_FILE")"
ERR_FILE_Q="$(printf '%q' "$ERR_FILE")"
START_SCRIPT_Q="$(printf '%q' "$START_SCRIPT")"
UP_SCRIPT_Q="$(printf '%q' "$UP_SCRIPT")"
DOWN_SCRIPT_Q="$(printf '%q' "$DOWN_SCRIPT")"
SERVERS_SCRIPT_Q="$(printf '%q' "$SERVERS_SCRIPT")"

cat > "$START_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RUNTIME_EXE=$RUNTIME_EXE_Q
PROFILES_PATH=$PROFILES_PATH_Q
STOP_FILE=$STOP_FILE_Q
rm -f "\$STOP_FILE"
ARGS=(--profiles "\$PROFILES_PATH" --stop-file "\$STOP_FILE")
add_bypass_ip() {
  local ip="\$1"
  if [[ -n "\$ip" ]]; then ARGS+=(--bypass-ip "\$ip"); fi
}
if [[ -n "\${SSH_CLIENT:-}" ]]; then add_bypass_ip "\${SSH_CLIENT%% *}"; fi
if command -v ss >/dev/null 2>&1; then
  while read -r peer; do add_bypass_ip "\$peer"; done < <(
    ss -Htn state established 2>/dev/null |
      awk '\$4 ~ /:22$/ {print \$5}' |
      sed -E 's/^\\[?([0-9.]+)\\]?:[0-9]+$/\\1/' |
      sort -u
  )
fi
exec "\$RUNTIME_EXE" "\${ARGS[@]}"
EOF

cat > "$UP_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$(id -u)" != "0" ]]; then echo "Run this command with sudo/root." >&2; exit 1; fi
PID_FILE=$PID_FILE_Q
STOP_FILE=$STOP_FILE_Q
LOG_FILE=$LOG_FILE_Q
ERR_FILE=$ERR_FILE_Q
START_SCRIPT=$START_SCRIPT_Q
if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
  if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
    echo "pyvpn client is already running with PID \$PID"
    exit 0
  fi
  rm -f "\$PID_FILE"
fi
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet pyvpn-client.service; then
  echo "An older system-wide pyvpn client is running. Disconnect it before starting this version." >&2
  exit 1
fi
if command -v pgrep >/dev/null 2>&1 && pgrep -f '[p]yvpn-client( |$)' >/dev/null 2>&1; then
  echo "Another pyvpn client is running. Disconnect it before starting this version." >&2
  exit 1
fi
rm -f "\$STOP_FILE" "\$PID_FILE"
nohup "\$START_SCRIPT" >"\$LOG_FILE" 2>"\$ERR_FILE" &
PID="\$!"
echo "\$PID" > "\$PID_FILE"
sleep 2
if ! kill -0 "\$PID" >/dev/null 2>&1; then
  if [[ -f "\$LOG_FILE" ]]; then tail -n 80 "\$LOG_FILE"; fi
  if [[ -f "\$ERR_FILE" ]]; then tail -n 80 "\$ERR_FILE" >&2; fi
  rm -f "\$PID_FILE"
  echo "pyvpn client failed to start" >&2
  exit 1
fi
echo "pyvpn client started in the background with PID \$PID"
echo "Log: \$LOG_FILE"
echo "Error log: \$ERR_FILE"
EOF

cat > "$DOWN_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$(id -u)" != "0" ]]; then echo "Run this command with sudo/root." >&2; exit 1; fi
PID_FILE=$PID_FILE_Q
STOP_FILE=$STOP_FILE_Q
if [[ -f "\$PID_FILE" ]]; then PID="\$(cat "\$PID_FILE")"; else PID=""; fi
if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
  touch "\$STOP_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "\$PID" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  if kill -0 "\$PID" >/dev/null 2>&1; then kill "\$PID" >/dev/null 2>&1 || true; fi
  sleep 1
  if kill -0 "\$PID" >/dev/null 2>&1; then kill -9 "\$PID" >/dev/null 2>&1 || true; fi
fi
rm -f "\$PID_FILE" "\$STOP_FILE"
echo "pyvpn client is stopped"
EOF

cat > "$STATUS_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PID_FILE=$PID_FILE_Q
LOG_FILE=$LOG_FILE_Q
ERR_FILE=$ERR_FILE_Q
RUNTIME_EXE=$RUNTIME_EXE_Q
PROFILES_PATH=$PROFILES_PATH_Q
if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
  if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
    echo "pyvpn client is running with PID \$PID"
  else
    echo "pyvpn client PID file exists, but the process is not running"
  fi
else
  echo "pyvpn client is not running"
fi
"\$RUNTIME_EXE" servers --file "\$PROFILES_PATH" show
echo "Log: \$LOG_FILE"
if [[ -f "\$LOG_FILE" ]]; then tail -n 40 "\$LOG_FILE"; fi
echo "Error log: \$ERR_FILE"
if [[ -f "\$ERR_FILE" ]]; then tail -n 40 "\$ERR_FILE"; fi
EOF

cat > "$SERVERS_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
RUNTIME_EXE=$RUNTIME_EXE_Q
PROFILES_PATH=$PROFILES_PATH_Q
exec "\$RUNTIME_EXE" servers --file "\$PROFILES_PATH" "\$@"
EOF

cat > "$SWITCH_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\$(id -u)" != "0" ]]; then echo "Run this command with sudo/root." >&2; exit 1; fi
if [[ \$# -ne 1 ]]; then echo "usage: sudo pyvpn-client-switch SERVER_ID" >&2; exit 2; fi
DOWN_SCRIPT=$DOWN_SCRIPT_Q
UP_SCRIPT=$UP_SCRIPT_Q
SERVERS_SCRIPT=$SERVERS_SCRIPT_Q
"\$SERVERS_SCRIPT" show "\$1" >/dev/null
"\$DOWN_SCRIPT"
"\$SERVERS_SCRIPT" use "\$1"
"\$UP_SCRIPT"
EOF

chmod 755 "$START_SCRIPT" "$UP_SCRIPT" "$DOWN_SCRIPT" "$STATUS_SCRIPT" "$SERVERS_SCRIPT" "$SWITCH_SCRIPT"
chown root:root "$START_SCRIPT" "$UP_SCRIPT" "$DOWN_SCRIPT" "$STATUS_SCRIPT" "$SERVERS_SCRIPT" "$SWITCH_SCRIPT"
if [[ "$WAS_ACTIVE" == "1" ]]; then "$UP_SCRIPT"; fi
trap - ERR
rm -rf "$BACKUP_DIR"

echo
echo "pyvpn offline Linux client $(metadata_value VERSION) installed."
echo "Install directory: $INSTALL_DIR"
echo "Server profiles: $PROFILES_PATH"
echo "Older system-wide installations were left unchanged."
echo "Connect:             sudo $UP_SCRIPT"
echo "Disconnect:          sudo $DOWN_SCRIPT"
echo "Servers and latency: sudo $SERVERS_SCRIPT list"
echo "Switch server:       sudo $SWITCH_SCRIPT <server_id>"
echo "Status:              sudo $STATUS_SCRIPT"
