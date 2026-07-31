#!/usr/bin/env bash
set -Eeuo pipefail

SERVER_HOST=""
TOKEN=""
CERT_FINGERPRINT=""
CONTROL_PORT="8443"
INSTALL_DIR="/opt/pyvpn-client"
CONFIG_DIR="/etc/pyvpn"
TUN_NAME="pyvpn0"
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
if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required to verify the offline package." >&2
  exit 1
fi
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
if [[ "$TUN_NAME" == "pyvpn0" && -n "$EXISTING_TUN" ]]; then TUN_NAME="$EXISTING_TUN"; fi
if [[ "$MTU" == "1280" && -n "$EXISTING_MTU" ]]; then MTU="$EXISTING_MTU"; fi
if [[ "$NO_DNS_SET" == "0" && -n "$EXISTING_NO_DNS" ]]; then NO_DNS="$EXISTING_NO_DNS"; fi
if [[ "${#BYPASS_IPS[@]}" -eq 0 && -n "$EXISTING_BYPASS" ]]; then
  OLD_IFS="$IFS"
  IFS=","
  read -r -a BYPASS_IPS <<< "$EXISTING_BYPASS"
  IFS="$OLD_IFS"
fi

if [[ -z "$SERVER_HOST" ]]; then
  read -r -p "Server host or IP: " SERVER_HOST
fi
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

if [[ -n "${SSH_CLIENT:-}" ]]; then
  BYPASS_IPS+=("${SSH_CLIENT%% *}")
fi
for bypass_ip in "${BYPASS_IPS[@]}"; do
  [[ -z "$bypass_ip" ]] || validate_env_value "bypass IP" "$bypass_ip"
done
BYPASS_IPS_CSV="$(IFS=,; echo "${BYPASS_IPS[*]}")"

PAYLOAD_DIR="$PACKAGE_ROOT/payload/pyvpn-client"
PAYLOAD_EXE="$PAYLOAD_DIR/pyvpn-client"
if [[ ! -x "$PAYLOAD_EXE" ]]; then
  echo "Bundled pyvpn-client is missing or not executable." >&2
  exit 1
fi
"$PAYLOAD_EXE" --help >/dev/null

RUNTIME="$INSTALL_DIR/runtime"
RUNTIME_NEW="$INSTALL_DIR/runtime.new"
RUNTIME_PREVIOUS="$INSTALL_DIR/runtime.previous"
BACKUP_DIR="$(mktemp -d /tmp/pyvpn-offline-client.XXXXXX)"
WAS_ACTIVE="0"
if systemctl is-active --quiet pyvpn-client.service; then
  WAS_ACTIVE="1"
fi

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

backup_file "$ENV_PATH" "client.env"
backup_file "/etc/systemd/system/pyvpn-client.service" "service"
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
  restore_file "/etc/systemd/system/pyvpn-client.service" "service"
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
  systemctl daemon-reload >/dev/null 2>&1
  if [[ "$WAS_ACTIVE" == "1" ]]; then systemctl start pyvpn-client.service >/dev/null 2>&1; fi
  rm -rf "$BACKUP_DIR"
  echo "Offline client installation failed; the previous installation was restored." >&2
  exit "$exit_code"
}
trap rollback ERR

if [[ "$WAS_ACTIVE" == "1" ]]; then systemctl stop pyvpn-client.service; fi
mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" /usr/local/bin
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
chown root:root "$ENV_PATH"
chmod 600 "$ENV_PATH"

cat > /usr/local/bin/pyvpn-client-start <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$ENV_PATH"
ARGS=(
  --server-host "\$PYVPN_SERVER_HOST"
  --control-port "\$PYVPN_CONTROL_PORT"
  --cert-fingerprint "\$PYVPN_CERT_FINGERPRINT"
  --tun "\$PYVPN_TUN"
  --mtu "\$PYVPN_MTU"
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
if command -v ss >/dev/null 2>&1; then
  while read -r peer; do add_bypass_ip "\$peer"; done < <(
    ss -Htn state established 2>/dev/null |
      awk '\$4 ~ /:22$/ {print \$5}' |
      sed -E 's/^\\[?([0-9.]+)\\]?:[0-9]+$/\\1/' |
      sort -u
  )
fi
if [[ "\${PYVPN_NO_DNS:-0}" == "1" ]]; then ARGS+=(--no-dns); fi
exec env PYVPN_TOKEN="\$PYVPN_TOKEN" "$RUNTIME/pyvpn-client" "\${ARGS[@]}"
EOF
chmod 755 /usr/local/bin/pyvpn-client-start

cat > /etc/systemd/system/pyvpn-client.service <<'EOF'
[Unit]
Description=pyvpn client
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/pyvpn-client-start
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /usr/local/bin/pyvpn-client-up <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl start pyvpn-client.service
systemctl --no-pager --full status pyvpn-client.service
EOF
cat > /usr/local/bin/pyvpn-client-down <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl stop pyvpn-client.service
systemctl --no-pager --full status pyvpn-client.service || true
EOF
cat > /usr/local/bin/pyvpn-client-status <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl --no-pager --full status pyvpn-client.service
EOF
chmod 755 /usr/local/bin/pyvpn-client-up /usr/local/bin/pyvpn-client-down
chmod 755 /usr/local/bin/pyvpn-client-status

systemctl daemon-reload
if [[ "$WAS_ACTIVE" == "1" ]]; then
  systemctl start pyvpn-client.service
  systemctl is-active --quiet pyvpn-client.service
fi
trap - ERR
rm -rf "$BACKUP_DIR"

echo
echo "pyvpn offline Linux client $(metadata_value VERSION) installed."
echo "Connect:    sudo pyvpn-client-up"
echo "Disconnect: sudo pyvpn-client-down"
echo "Status:     sudo pyvpn-client-status"
