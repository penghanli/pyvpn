#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_HOST=""
TOKEN=""
CERT_FINGERPRINT=""
CONTROL_PORT="8443"
INSTALL_DIR="/opt/pyvpn-client"
CONFIG_DIR="/Library/Application Support/pyvpn"
RUN_DIR="/var/run/pyvpn"
LOG_DIR="/var/log/pyvpn"
TUN_NAME="auto"
MTU="1280"
NO_DNS="0"
NO_DNS_SET="0"
BYPASS_IPS=()

usage() {
  cat <<'EOF'
Usage:
  sudo ./install-client.sh [options]

Options:
  --server-host HOST
  --token TOKEN
  --cert-fingerprint FP
  --control-port PORT
  --bypass-ip IP
  --install-dir DIR
  --config-dir DIR
  --run-dir DIR
  --log-dir DIR
  --tun NAME
  --mtu MTU
  --no-dns
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-host) SERVER_HOST="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --cert-fingerprint) CERT_FINGERPRINT="${2:-}"; shift 2 ;;
    --control-port) CONTROL_PORT="${2:-}"; shift 2 ;;
    --bypass-ip) BYPASS_IPS+=("${2:-}"); shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:-}"; shift 2 ;;
    --run-dir) RUN_DIR="${2:-}"; shift 2 ;;
    --log-dir) LOG_DIR="${2:-}"; shift 2 ;;
    --tun) TUN_NAME="${2:-}"; shift 2 ;;
    --mtu) MTU="${2:-}"; shift 2 ;;
    --no-dns) NO_DNS="1"; NO_DNS_SET="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this installer with sudo/root." >&2
  exit 1
fi
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This offline package supports macOS only." >&2
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
for command_name in shasum route ifconfig networksetup ditto sw_vers; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required macOS command is missing: $command_name" >&2
    exit 1
  fi
done
MACOS_VERSION="$(sw_vers -productVersion)"
MACOS_MAJOR="${MACOS_VERSION%%.*}"
if [[ ! "$MACOS_MAJOR" =~ ^[0-9]+$ || "$MACOS_MAJOR" -lt 12 ]]; then
  echo "This offline package requires macOS 12 or later; detected $MACOS_VERSION." >&2
  exit 1
fi
(cd "$PACKAGE_ROOT" && shasum -a 256 -c SHA256SUMS >/dev/null)

PACKAGE_PLATFORM="$(metadata_value PLATFORM)"
PACKAGE_ARCH="$(metadata_value ARCH)"
PACKAGE_ROLE="$(metadata_value ROLE)"
if [[ "$PACKAGE_PLATFORM" != "macos" || "$PACKAGE_ROLE" != "client" ]]; then
  echo "This is not a macOS client package." >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64) ACTUAL_ARCH="x86_64" ;;
  arm64) ACTUAL_ARCH="arm64" ;;
  *) echo "Unsupported macOS architecture: $(uname -m)" >&2; exit 1 ;;
esac
if [[ "$ACTUAL_ARCH" != "$PACKAGE_ARCH" ]]; then
  echo "Wrong package architecture: package=$PACKAGE_ARCH machine=$ACTUAL_ARCH" >&2
  exit 1
fi

for path_value in "$INSTALL_DIR" "$CONFIG_DIR" "$RUN_DIR" "$LOG_DIR"; do
  case "$path_value" in
    /*) ;;
    *) echo "Installation paths must be absolute." >&2; exit 2 ;;
  esac
done

xattr -dr com.apple.quarantine "$PACKAGE_ROOT" >/dev/null 2>&1 || true
ENV_PATH="$CONFIG_DIR/client.env"
existing_value() {
  local name="$1"
  if [[ -f "$ENV_PATH" ]]; then
    sed -n "s/^${name}=//p" "$ENV_PATH" | tail -n 1
  fi
}

if [[ -z "$SERVER_HOST" ]]; then SERVER_HOST="$(existing_value PYVPN_SERVER_HOST)"; fi
if [[ -z "$TOKEN" ]]; then TOKEN="$(existing_value PYVPN_TOKEN)"; fi
if [[ -z "$CERT_FINGERPRINT" ]]; then
  CERT_FINGERPRINT="$(existing_value PYVPN_CERT_FINGERPRINT)"
fi
EXISTING_CONTROL_PORT="$(existing_value PYVPN_CONTROL_PORT)"
EXISTING_TUN="$(existing_value PYVPN_TUN)"
EXISTING_MTU="$(existing_value PYVPN_MTU)"
EXISTING_NO_DNS="$(existing_value PYVPN_NO_DNS)"
EXISTING_BYPASS="$(existing_value PYVPN_BYPASS_IPS)"
if [[ "$CONTROL_PORT" == "8443" && -n "$EXISTING_CONTROL_PORT" ]]; then
  CONTROL_PORT="$EXISTING_CONTROL_PORT"
fi
if [[ "$TUN_NAME" == "auto" && -n "$EXISTING_TUN" ]]; then TUN_NAME="$EXISTING_TUN"; fi
if [[ "$MTU" == "1280" && -n "$EXISTING_MTU" ]]; then MTU="$EXISTING_MTU"; fi
if [[ "$NO_DNS_SET" == "0" && -n "$EXISTING_NO_DNS" ]]; then NO_DNS="$EXISTING_NO_DNS"; fi
if [[ "${#BYPASS_IPS[@]}" -eq 0 && -n "$EXISTING_BYPASS" ]]; then
  OLD_IFS="$IFS"
  IFS=","
  read -r -a BYPASS_IPS <<< "$EXISTING_BYPASS"
  IFS="$OLD_IFS"
fi

if [[ -z "$SERVER_HOST" ]]; then read -r -p "Server host or IP: " SERVER_HOST; fi
if [[ -z "$TOKEN" ]]; then
  read -r -s -p "Shared token: " TOKEN
  echo
fi
if [[ -z "$CERT_FINGERPRINT" ]]; then
  read -r -p "Certificate fingerprint (sha256:...): " CERT_FINGERPRINT
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

validate_env_value() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._:@%+=,/-]+$ ]]; then
    echo "$name contains unsupported characters: $value" >&2
    exit 2
  fi
}
validate_env_value "server host" "$SERVER_HOST"
validate_env_value "token" "$TOKEN"
validate_env_value "certificate fingerprint" "$CERT_FINGERPRINT"
validate_env_value "control port" "$CONTROL_PORT"
validate_env_value "tun name" "$TUN_NAME"
validate_env_value "MTU" "$MTU"
if [[ -n "${SSH_CLIENT:-}" ]]; then BYPASS_IPS+=("${SSH_CLIENT%% *}"); fi
for bypass_ip in "${BYPASS_IPS[@]}"; do
  [[ -z "$bypass_ip" ]] || validate_env_value "bypass IP" "$bypass_ip"
done
BYPASS_IPS_CSV="$(IFS=,; echo "${BYPASS_IPS[*]}")"

PAYLOAD_DIR="$PACKAGE_ROOT/payload"
PAYLOAD_EXE="$PAYLOAD_DIR/pyvpn-client/pyvpn-client"
PAYLOAD_TOOLS="$PAYLOAD_DIR/pyvpn-client-tools/pyvpn-client-tools"
if [[ ! -x "$PAYLOAD_EXE" || ! -x "$PAYLOAD_TOOLS" ]]; then
  echo "Bundled macOS client runtime is missing or not executable." >&2
  exit 1
fi
"$PAYLOAD_EXE" --help >/dev/null
"$PAYLOAD_TOOLS" --help >/dev/null

PID_FILE="$RUN_DIR/client.pid"
WAS_ACTIVE="0"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" >/dev/null 2>&1; then WAS_ACTIVE="1"; fi
fi

RUNTIME="$INSTALL_DIR/runtime"
RUNTIME_NEW="$INSTALL_DIR/runtime.new"
RUNTIME_PREVIOUS="$INSTALL_DIR/runtime.previous"
BACKUP_DIR="$(mktemp -d /tmp/pyvpn-offline-macos.XXXXXX)"

backup_file() {
  local source="$1"
  local key="$2"
  if [[ -f "$source" ]]; then
    cp -p "$source" "$BACKUP_DIR/$key"
    echo 1 > "$BACKUP_DIR/$key.exists"
  else
    echo 0 > "$BACKUP_DIR/$key.exists"
  fi
}
restore_file() {
  local target="$1"
  local key="$2"
  if [[ "$(cat "$BACKUP_DIR/$key.exists")" == "1" ]]; then
    mkdir -p "$(dirname "$target")"
    cp -p "$BACKUP_DIR/$key" "$target"
  else
    rm -f "$target"
  fi
}

backup_file "$ENV_PATH" "client.env"
backup_file "/usr/local/bin/pyvpn-client-start" "start"
backup_file "/usr/local/bin/pyvpn-client-up" "up"
backup_file "/usr/local/bin/pyvpn-client-down" "down"
backup_file "/usr/local/bin/pyvpn-client-status" "status"

OLD_RUNTIME_MOVED="0"
NEW_RUNTIME_INSTALLED="0"
rollback() {
  local exit_code=$?
  trap - ERR
  set +e
  restore_file "$ENV_PATH" "client.env"
  restore_file "/usr/local/bin/pyvpn-client-start" "start"
  restore_file "/usr/local/bin/pyvpn-client-up" "up"
  restore_file "/usr/local/bin/pyvpn-client-down" "down"
  restore_file "/usr/local/bin/pyvpn-client-status" "status"
  rm -rf "$RUNTIME_NEW"
  if [[ "$NEW_RUNTIME_INSTALLED" == "1" ]]; then
    rm -rf "$RUNTIME"
  fi
  if [[ "$OLD_RUNTIME_MOVED" == "1" && -d "$RUNTIME_PREVIOUS" ]]; then
    rm -rf "$RUNTIME"
    mv "$RUNTIME_PREVIOUS" "$RUNTIME"
  fi
  if [[ "$WAS_ACTIVE" == "1" && -x /usr/local/bin/pyvpn-client-up ]]; then
    /usr/local/bin/pyvpn-client-up >/dev/null 2>&1
  fi
  rm -rf "$BACKUP_DIR"
  echo "Offline macOS client installation failed; the previous installation was restored." >&2
  exit "$exit_code"
}
trap rollback ERR

if [[ -x /usr/local/bin/pyvpn-client-down ]]; then
  /usr/local/bin/pyvpn-client-down || true
fi
if [[ "$WAS_ACTIVE" == "1" ]] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
  echo "The existing pyvpn client did not stop." >&2
  false
fi
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$RUN_DIR" "$LOG_DIR" /usr/local/bin
rm -rf "$RUNTIME_NEW"
mkdir -p "$RUNTIME_NEW"
ditto "$PAYLOAD_DIR/pyvpn-client" "$RUNTIME_NEW/pyvpn-client"
ditto "$PAYLOAD_DIR/pyvpn-client-tools" "$RUNTIME_NEW/pyvpn-client-tools"
chown -R root:wheel "$RUNTIME_NEW"
chmod -R go-w "$RUNTIME_NEW"
"$RUNTIME_NEW/pyvpn-client/pyvpn-client" --help >/dev/null
"$RUNTIME_NEW/pyvpn-client-tools/pyvpn-client-tools" --help >/dev/null
rm -rf "$RUNTIME_PREVIOUS"
if [[ -d "$RUNTIME" ]]; then
  mv "$RUNTIME" "$RUNTIME_PREVIOUS"
  OLD_RUNTIME_MOVED="1"
fi
mv "$RUNTIME_NEW" "$RUNTIME"
NEW_RUNTIME_INSTALLED="1"

cat > "$ENV_PATH" <<EOF
PYVPN_SERVER_HOST=$SERVER_HOST
PYVPN_CONTROL_PORT=$CONTROL_PORT
PYVPN_TOKEN=$TOKEN
PYVPN_CERT_FINGERPRINT=$CERT_FINGERPRINT
PYVPN_TUN=$TUN_NAME
PYVPN_MTU=$MTU
PYVPN_NO_DNS=$NO_DNS
PYVPN_BYPASS_IPS=$BYPASS_IPS_CSV
EOF
chown root:wheel "$ENV_PATH"
chmod 600 "$ENV_PATH"

cat > /usr/local/bin/pyvpn-client-start <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$ENV_PATH"
STOP_FILE="$RUN_DIR/client.stop"
mkdir -p "$RUN_DIR"
rm -f "\$STOP_FILE"
ARGS=(
  --server-host "\$PYVPN_SERVER_HOST"
  --control-port "\$PYVPN_CONTROL_PORT"
  --cert-fingerprint "\$PYVPN_CERT_FINGERPRINT"
  --tun "\$PYVPN_TUN"
  --mtu "\$PYVPN_MTU"
  --stop-file "\$STOP_FILE"
)
add_bypass_ip() {
  local ip="\$1"
  if [[ -n "\$ip" && "\$ip" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$ ]]; then
    ARGS+=(--bypass-ip "\$ip")
  fi
}
if [[ -n "\${PYVPN_BYPASS_IPS:-}" ]]; then
  IFS=',' read -ra SAVED_BYPASS_IPS <<< "\$PYVPN_BYPASS_IPS"
  for ip in "\${SAVED_BYPASS_IPS[@]}"; do add_bypass_ip "\$ip"; done
fi
if [[ -n "\${SSH_CLIENT:-}" ]]; then add_bypass_ip "\${SSH_CLIENT%% *}"; fi
if [[ "\${PYVPN_NO_DNS:-0}" == "1" ]]; then ARGS+=(--no-dns); fi
exec env PYVPN_TOKEN="\$PYVPN_TOKEN" "$RUNTIME/pyvpn-client/pyvpn-client" "\${ARGS[@]}"
EOF
chmod 755 /usr/local/bin/pyvpn-client-start

cat > /usr/local/bin/pyvpn-client-up <<EOF
#!/usr/bin/env bash
set -euo pipefail
PID_FILE="$RUN_DIR/client.pid"
STOP_FILE="$RUN_DIR/client.stop"
LOG_FILE="$LOG_DIR/client.log"
ERR_FILE="$LOG_DIR/client.err.log"
mkdir -p "$RUN_DIR" "$LOG_DIR"
if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
  if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
    echo "pyvpn client is already running with PID \$PID"
    exit 0
  fi
fi
rm -f "\$STOP_FILE" "\$PID_FILE"
nohup /usr/local/bin/pyvpn-client-start >"\$LOG_FILE" 2>"\$ERR_FILE" &
PID="\$!"
echo "\$PID" > "\$PID_FILE"
ROUTE_OK="0"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  if ! kill -0 "\$PID" >/dev/null 2>&1; then
    [[ -f "\$LOG_FILE" ]] && tail -n 80 "\$LOG_FILE"
    [[ -f "\$ERR_FILE" ]] && tail -n 80 "\$ERR_FILE"
    rm -f "\$PID_FILE"
    echo "pyvpn client failed to start" >&2
    exit 1
  fi
  if route -n get 1.1.1.1 2>/dev/null | grep -Eq 'interface:[[:space:]]+utun[0-9]+'; then
    ROUTE_OK="1"
    break
  fi
done
if [[ "\$ROUTE_OK" != "1" ]]; then
  echo "pyvpn client started, but macOS routing did not switch to utun." >&2
  route -n get 1.1.1.1 >&2 || true
  [[ -f "\$LOG_FILE" ]] && tail -n 80 "\$LOG_FILE" >&2
  [[ -f "\$ERR_FILE" ]] && tail -n 80 "\$ERR_FILE" >&2
  touch "\$STOP_FILE" >/dev/null 2>&1 || true
  sleep 2
  kill "\$PID" >/dev/null 2>&1 || true
  rm -f "\$PID_FILE"
  exit 1
fi
echo "pyvpn client started in the background with PID \$PID"
echo "Log: \$LOG_FILE"
echo "Error log: \$ERR_FILE"
EOF
chmod 755 /usr/local/bin/pyvpn-client-up

cat > /usr/local/bin/pyvpn-client-down <<EOF
#!/usr/bin/env bash
set -euo pipefail
PID_FILE="$RUN_DIR/client.pid"
STOP_FILE="$RUN_DIR/client.stop"
DNS_STATE="/var/run/pyvpn/macos-dns-state.json"
if [[ -f "\$PID_FILE" ]]; then PID="\$(cat "\$PID_FILE")"; else PID=""; fi
if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
  touch "\$STOP_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "\$PID" >/dev/null 2>&1; then break; fi
    sleep 1
  done
  if kill -0 "\$PID" >/dev/null 2>&1; then kill "\$PID" >/dev/null 2>&1 || true; fi
  sleep 2
  if kill -0 "\$PID" >/dev/null 2>&1; then kill -9 "\$PID" >/dev/null 2>&1 || true; fi
  echo "pyvpn client stopped"
else
  echo "pyvpn client is not running"
fi
rm -f "\$PID_FILE" "\$STOP_FILE"
route -n delete -net 0.0.0.0 -netmask 128.0.0.0 >/dev/null 2>&1 || true
route -n delete -net 128.0.0.0 -netmask 128.0.0.0 >/dev/null 2>&1 || true
if [[ -f "$ENV_PATH" ]]; then
  source "$ENV_PATH"
  route -n delete -host "\$PYVPN_SERVER_HOST" >/dev/null 2>&1 || true
  SERVER_IP="\$("$RUNTIME/pyvpn-client-tools/pyvpn-client-tools" resolve "\$PYVPN_SERVER_HOST" 2>/dev/null || true)"
  if [[ -n "\$SERVER_IP" ]]; then
    route -n delete -host "\$SERVER_IP" >/dev/null 2>&1 || true
  fi
fi
"$RUNTIME/pyvpn-client-tools/pyvpn-client-tools" restore-macos-dns "\$DNS_STATE" || true
EOF
chmod 755 /usr/local/bin/pyvpn-client-down

cat > /usr/local/bin/pyvpn-client-status <<EOF
#!/usr/bin/env bash
set -euo pipefail
PID_FILE="$RUN_DIR/client.pid"
LOG_FILE="$LOG_DIR/client.log"
ERR_FILE="$LOG_DIR/client.err.log"
if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
  if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
    echo "pyvpn client is running with PID \$PID"
  else
    echo "pyvpn client is not running"
  fi
else
  echo "pyvpn client is not running"
fi
echo "Log: \$LOG_FILE"
echo "Error log: \$ERR_FILE"
route -n get 1.1.1.1 || true
netstat -rn -f inet | grep -E '(^default|^0/1|^128\\.0/1|10\\.8\\.)' || true
if [[ -f "\$ERR_FILE" ]]; then tail -n 40 "\$ERR_FILE"; fi
EOF
chmod 755 /usr/local/bin/pyvpn-client-status

if [[ "$WAS_ACTIVE" == "1" ]]; then /usr/local/bin/pyvpn-client-up; fi
trap - ERR
rm -rf "$BACKUP_DIR"

echo
echo "pyvpn offline macOS client $(metadata_value VERSION) installed."
echo "Connect:    sudo pyvpn-client-up"
echo "Disconnect: sudo pyvpn-client-down"
echo "Status:     sudo pyvpn-client-status"
