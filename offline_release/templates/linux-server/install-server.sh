#!/usr/bin/env bash
set -Eeuo pipefail

PUBLIC_HOST=""
TOKEN=""
CONTROL_PORT="8443"
UDP_PORT="8444"
DNS="1.1.1.1"
MAX_CLIENTS="3"
INSTALL_DIR="/opt/pyvpn"
CONFIG_DIR="/etc/pyvpn"
FORCE_CERT="0"

CONTROL_PORT_SET="0"
UDP_PORT_SET="0"
DNS_SET="0"
MAX_CLIENTS_SET="0"

usage() {
  cat <<'EOF'
Usage:
  sudo ./install-server.sh [options]

Options:
  --public-host HOST
  --token TOKEN
  --control-port PORT
  --udp-port PORT
  --dns IP
  --max-clients N
  --install-dir DIR
  --config-dir DIR
  --force-cert
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-host) PUBLIC_HOST="${2:-}"; shift 2 ;;
    --token) TOKEN="${2:-}"; shift 2 ;;
    --control-port) CONTROL_PORT="${2:-}"; CONTROL_PORT_SET="1"; shift 2 ;;
    --udp-port) UDP_PORT="${2:-}"; UDP_PORT_SET="1"; shift 2 ;;
    --dns) DNS="${2:-}"; DNS_SET="1"; shift 2 ;;
    --max-clients) MAX_CLIENTS="${2:-}"; MAX_CLIENTS_SET="1"; shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:-}"; shift 2 ;;
    --force-cert) FORCE_CERT="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this installer with sudo/root." >&2
  exit 1
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This offline server package supports Linux only." >&2
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
if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required to verify the offline package." >&2
  exit 1
fi
(cd "$PACKAGE_ROOT" && sha256sum --check --quiet SHA256SUMS)

PACKAGE_PLATFORM="$(metadata_value PLATFORM)"
PACKAGE_ARCH="$(metadata_value ARCH)"
PACKAGE_ROLE="$(metadata_value ROLE)"
if [[ "$PACKAGE_PLATFORM" != "linux" || "$PACKAGE_ROLE" != "server" ]]; then
  echo "This is not a Linux server package." >&2
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

for command_name in ip systemctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required system command is missing: $command_name" >&2
    exit 1
  fi
done
if [[ ! -d /run/systemd/system ]]; then
  echo "systemd is not running on this Linux system." >&2
  exit 1
fi
if ! command -v nft >/dev/null 2>&1 && ! command -v iptables >/dev/null 2>&1; then
  echo "The server requires nft or iptables for NAT." >&2
  exit 1
fi
if [[ ! -e /dev/net/tun ]]; then
  echo "/dev/net/tun is missing. Enable the Linux TUN driver before installation." >&2
  exit 1
fi
case "$INSTALL_DIR" in
  /*) ;;
  *) echo "--install-dir must be an absolute path." >&2; exit 2 ;;
esac
case "$CONFIG_DIR" in
  /*) ;;
  *) echo "--config-dir must be an absolute path." >&2; exit 2 ;;
esac

ENV_PATH="$CONFIG_DIR/server.env"
existing_value() {
  local name="$1"
  if [[ -f "$ENV_PATH" ]]; then
    sed -n "s/^${name}=//p" "$ENV_PATH" | tail -n 1
  fi
}

if [[ -z "$PUBLIC_HOST" ]]; then PUBLIC_HOST="$(existing_value PYVPN_PUBLIC_HOST)"; fi
if [[ -z "$TOKEN" ]]; then TOKEN="$(existing_value PYVPN_TOKEN)"; fi
EXISTING_CONTROL_PORT="$(existing_value PYVPN_CONTROL_PORT)"
EXISTING_UDP_PORT="$(existing_value PYVPN_UDP_PORT)"
EXISTING_DNS="$(existing_value PYVPN_DNS)"
EXISTING_MAX_CLIENTS="$(existing_value PYVPN_MAX_CLIENTS)"
if [[ "$CONTROL_PORT_SET" == "0" && -n "$EXISTING_CONTROL_PORT" ]]; then
  CONTROL_PORT="$EXISTING_CONTROL_PORT"
fi
if [[ "$UDP_PORT_SET" == "0" && -n "$EXISTING_UDP_PORT" ]]; then UDP_PORT="$EXISTING_UDP_PORT"; fi
if [[ "$DNS_SET" == "0" && -n "$EXISTING_DNS" ]]; then DNS="$EXISTING_DNS"; fi
if [[ "$MAX_CLIENTS_SET" == "0" && -n "$EXISTING_MAX_CLIENTS" ]]; then
  MAX_CLIENTS="$EXISTING_MAX_CLIENTS"
fi

if [[ -z "$PUBLIC_HOST" ]]; then
  read -r -p "Server public IP or DNS name: " PUBLIC_HOST
fi
if [[ -z "$PUBLIC_HOST" ]]; then
  echo "Server public IP or DNS name is required." >&2
  exit 2
fi
if [[ -z "$TOKEN" && -t 0 ]]; then
  read -r -s -p "Shared token (leave empty to generate): " TOKEN
  echo
fi

validate_env_value() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._:@%+=,/-]+$ ]]; then
    echo "$name contains unsupported characters: $value" >&2
    exit 2
  fi
}
validate_env_value "public host" "$PUBLIC_HOST"
[[ -z "$TOKEN" ]] || validate_env_value "token" "$TOKEN"
validate_env_value "control port" "$CONTROL_PORT"
validate_env_value "UDP port" "$UDP_PORT"
validate_env_value "DNS" "$DNS"
validate_env_value "max clients" "$MAX_CLIENTS"
if [[ ! "$CONTROL_PORT" =~ ^[0-9]+$ || "$CONTROL_PORT" -lt 1 || "$CONTROL_PORT" -gt 65535 ]]; then
  echo "Control port must be from 1 to 65535." >&2
  exit 2
fi
if [[ ! "$UDP_PORT" =~ ^[0-9]+$ || "$UDP_PORT" -lt 1 || "$UDP_PORT" -gt 65535 ]]; then
  echo "UDP port must be from 1 to 65535." >&2
  exit 2
fi
if [[ ! "$MAX_CLIENTS" =~ ^[0-9]+$ || "$MAX_CLIENTS" -lt 1 || "$MAX_CLIENTS" -gt 10 ]]; then
  echo "Max clients must be from 1 to 10." >&2
  exit 2
fi

PAYLOAD_DIR="$PACKAGE_ROOT/payload"
PAYLOAD_SERVER="$PAYLOAD_DIR/pyvpn-server/pyvpn-server"
PAYLOAD_TOOLS="$PAYLOAD_DIR/pyvpn-tools/pyvpn-tools"
if [[ ! -x "$PAYLOAD_SERVER" || ! -x "$PAYLOAD_TOOLS" ]]; then
  echo "Bundled server runtime is missing or not executable." >&2
  exit 1
fi
"$PAYLOAD_SERVER" --help >/dev/null
"$PAYLOAD_TOOLS" --help >/dev/null

RUNTIME="$INSTALL_DIR/runtime"
RUNTIME_NEW="$INSTALL_DIR/runtime.new"
RUNTIME_PREVIOUS="$INSTALL_DIR/runtime.previous"
CERT_PATH="$CONFIG_DIR/server.crt"
KEY_PATH="$CONFIG_DIR/server.key"
FINGERPRINT_PATH="$CONFIG_DIR/server.fingerprint"
BACKUP_DIR="$(mktemp -d /tmp/pyvpn-offline-server.XXXXXX)"
WAS_ACTIVE="0"
if systemctl is-active --quiet pyvpn-server.service; then
  WAS_ACTIVE="1"
fi
WAS_ENABLED="0"
if systemctl is-enabled --quiet pyvpn-server.service; then WAS_ENABLED="1"; fi

backup_file() {
  local source="$1"
  local key="$2"
  if [[ -f "$source" ]]; then
    cp -a "$source" "$BACKUP_DIR/$key"
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
    cp -a "$BACKUP_DIR/$key" "$target"
  else
    rm -f "$target"
  fi
}

backup_file "$ENV_PATH" "server.env"
backup_file "$CERT_PATH" "server.crt"
backup_file "$KEY_PATH" "server.key"
backup_file "$FINGERPRINT_PATH" "server.fingerprint"
backup_file "/etc/systemd/system/pyvpn-server.service" "service"
backup_file "/usr/local/bin/pyvpn-server-restart" "restart"
backup_file "/usr/local/bin/pyvpn-server-status" "status"
backup_file "/usr/local/bin/pyvpn-server-logs" "logs"

OLD_RUNTIME_MOVED="0"
NEW_RUNTIME_INSTALLED="0"
rollback() {
  local exit_code=$?
  trap - ERR
  set +e
  restore_file "$ENV_PATH" "server.env"
  restore_file "$CERT_PATH" "server.crt"
  restore_file "$KEY_PATH" "server.key"
  restore_file "$FINGERPRINT_PATH" "server.fingerprint"
  restore_file "/etc/systemd/system/pyvpn-server.service" "service"
  restore_file "/usr/local/bin/pyvpn-server-restart" "restart"
  restore_file "/usr/local/bin/pyvpn-server-status" "status"
  restore_file "/usr/local/bin/pyvpn-server-logs" "logs"
  rm -rf "$RUNTIME_NEW"
  if [[ "$NEW_RUNTIME_INSTALLED" == "1" ]]; then
    rm -rf "$RUNTIME"
  fi
  if [[ "$OLD_RUNTIME_MOVED" == "1" && -d "$RUNTIME_PREVIOUS" ]]; then
    rm -rf "$RUNTIME"
    mv "$RUNTIME_PREVIOUS" "$RUNTIME"
  fi
  systemctl daemon-reload >/dev/null 2>&1
  if [[ "$WAS_ENABLED" == "1" ]]; then
    systemctl enable pyvpn-server.service >/dev/null 2>&1
  else
    systemctl disable pyvpn-server.service >/dev/null 2>&1
  fi
  if [[ "$WAS_ACTIVE" == "1" ]]; then systemctl start pyvpn-server.service >/dev/null 2>&1; fi
  rm -rf "$BACKUP_DIR"
  echo "Offline server installation failed; the previous installation was restored." >&2
  exit "$exit_code"
}
trap rollback ERR

if [[ "$WAS_ACTIVE" == "1" ]]; then systemctl stop pyvpn-server.service; fi
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" /usr/local/bin
rm -rf "$RUNTIME_NEW"
mkdir -p "$RUNTIME_NEW"
cp -a "$PAYLOAD_DIR/pyvpn-server" "$RUNTIME_NEW/pyvpn-server"
cp -a "$PAYLOAD_DIR/pyvpn-tools" "$RUNTIME_NEW/pyvpn-tools"
chown -R root:root "$RUNTIME_NEW"
chmod -R go-w "$RUNTIME_NEW"
"$RUNTIME_NEW/pyvpn-server/pyvpn-server" --help >/dev/null
"$RUNTIME_NEW/pyvpn-tools/pyvpn-tools" --help >/dev/null
rm -rf "$RUNTIME_PREVIOUS"
if [[ -d "$RUNTIME" ]]; then
  mv "$RUNTIME" "$RUNTIME_PREVIOUS"
  OLD_RUNTIME_MOVED="1"
fi
mv "$RUNTIME_NEW" "$RUNTIME"
NEW_RUNTIME_INSTALLED="1"

SERVER_EXE="$RUNTIME/pyvpn-server/pyvpn-server"
TOOLS_EXE="$RUNTIME/pyvpn-tools/pyvpn-tools"
if [[ -z "$TOKEN" ]]; then TOKEN="$("$TOOLS_EXE" token)"; fi
validate_env_value "token" "$TOKEN"

if [[ "$FORCE_CERT" == "1" || ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  "$TOOLS_EXE" cert \
    --cert "$CERT_PATH" \
    --key "$KEY_PATH" \
    --common-name "$PUBLIC_HOST"
fi
chown root:root "$CERT_PATH" "$KEY_PATH"
chmod 644 "$CERT_PATH"
chmod 600 "$KEY_PATH"
FINGERPRINT="$("$TOOLS_EXE" fingerprint --cert "$CERT_PATH")"
printf 'certificate fingerprint: %s\n' "$FINGERPRINT" > "$FINGERPRINT_PATH"
chown root:root "$FINGERPRINT_PATH"
chmod 644 "$FINGERPRINT_PATH"

LISTEN_HOST="$(existing_value PYVPN_LISTEN_HOST)"
TUN_NAME="$(existing_value PYVPN_TUN)"
SUBNET="$(existing_value PYVPN_SUBNET)"
SERVER_VIP="$(existing_value PYVPN_SERVER_VIP)"
CLIENT_VIP="$(existing_value PYVPN_CLIENT_VIP)"
MTU="$(existing_value PYVPN_MTU)"
SESSION_TIMEOUT="$(existing_value PYVPN_SESSION_TIMEOUT)"
[[ -n "$LISTEN_HOST" ]] || LISTEN_HOST="0.0.0.0"
[[ -n "$TUN_NAME" ]] || TUN_NAME="pyvpn0"
[[ -n "$SUBNET" ]] || SUBNET="10.8.0.0/24"
[[ -n "$SERVER_VIP" ]] || SERVER_VIP="10.8.0.1"
[[ -n "$CLIENT_VIP" ]] || CLIENT_VIP="10.8.0.2"
[[ -n "$MTU" ]] || MTU="1280"
[[ -n "$SESSION_TIMEOUT" ]] || SESSION_TIMEOUT="60"

cat > "$ENV_PATH" <<EOF
PYVPN_TOKEN=$TOKEN
PYVPN_LISTEN_HOST=$LISTEN_HOST
PYVPN_CONTROL_PORT=$CONTROL_PORT
PYVPN_UDP_PORT=$UDP_PORT
PYVPN_PUBLIC_HOST=$PUBLIC_HOST
PYVPN_CERT=$CERT_PATH
PYVPN_KEY=$KEY_PATH
PYVPN_TUN=$TUN_NAME
PYVPN_SUBNET=$SUBNET
PYVPN_SERVER_VIP=$SERVER_VIP
PYVPN_CLIENT_VIP=$CLIENT_VIP
PYVPN_DNS=$DNS
PYVPN_MTU=$MTU
PYVPN_SESSION_TIMEOUT=$SESSION_TIMEOUT
PYVPN_MAX_CLIENTS=$MAX_CLIENTS
EOF
chown root:root "$ENV_PATH"
chmod 600 "$ENV_PATH"

cat > /etc/systemd/system/pyvpn-server.service <<EOF
[Unit]
Description=pyvpn server
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
EnvironmentFile=$ENV_PATH
ExecStart=$SERVER_EXE --listen-host \${PYVPN_LISTEN_HOST} --control-port \${PYVPN_CONTROL_PORT} --udp-port \${PYVPN_UDP_PORT} --public-host \${PYVPN_PUBLIC_HOST} --cert \${PYVPN_CERT} --key \${PYVPN_KEY} --tun \${PYVPN_TUN} --subnet \${PYVPN_SUBNET} --server-vip \${PYVPN_SERVER_VIP} --client-vip \${PYVPN_CLIENT_VIP} --dns \${PYVPN_DNS} --mtu \${PYVPN_MTU} --session-timeout \${PYVPN_SESSION_TIMEOUT} --max-clients \${PYVPN_MAX_CLIENTS}
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/pyvpn-server-restart <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl restart pyvpn-server.service
systemctl --no-pager --full status pyvpn-server.service
EOF
cat > /usr/local/bin/pyvpn-server-status <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl --no-pager --full status pyvpn-server.service
EOF
cat > /usr/local/bin/pyvpn-server-logs <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
journalctl -u pyvpn-server.service -f
EOF
chmod 755 /usr/local/bin/pyvpn-server-restart /usr/local/bin/pyvpn-server-status
chmod 755 /usr/local/bin/pyvpn-server-logs

systemctl daemon-reload
systemctl enable --now pyvpn-server.service
systemctl is-active --quiet pyvpn-server.service
trap - ERR
rm -rf "$BACKUP_DIR"

echo
echo "pyvpn offline Linux server $(metadata_value VERSION) installed and started."
echo
echo "Client settings:"
echo "  server host: $PUBLIC_HOST"
echo "  control port: $CONTROL_PORT"
echo "  max clients: $MAX_CLIENTS"
echo "  token: $TOKEN"
echo "  cert fingerprint: $FINGERPRINT"
echo
echo "Server commands:"
echo "  sudo pyvpn-server-status"
echo "  sudo pyvpn-server-logs"
echo "  sudo pyvpn-server-restart"
