#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/linux/install-client.sh \
    --server-host <server-ip-or-domain> \
    --token <shared-token> \
    --cert-fingerprint 'sha256:<fingerprint>'

Options:
  --server-host HOST        Server public IP or DNS name. Required.
  --token TOKEN             Shared token printed by install-server.sh. Required.
  --cert-fingerprint FP     Server certificate fingerprint. Required.
  --control-port PORT       TLS control port. Default: 8443.
  --install-dir DIR         Virtualenv install directory. Default: /opt/pyvpn-client.
  --config-dir DIR          Runtime config directory. Default: /etc/pyvpn.
  --no-dns                  Do not change client DNS while connected.

After installation:
  sudo pyvpn-client-start
EOF
}

SERVER_HOST=""
TOKEN=""
CERT_FINGERPRINT=""
CONTROL_PORT="8443"
INSTALL_DIR="/opt/pyvpn-client"
CONFIG_DIR="/etc/pyvpn"
NO_DNS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-host)
      SERVER_HOST="${2:-}"
      shift 2
      ;;
    --token)
      TOKEN="${2:-}"
      shift 2
      ;;
    --cert-fingerprint)
      CERT_FINGERPRINT="${2:-}"
      shift 2
      ;;
    --control-port)
      CONTROL_PORT="${2:-}"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --config-dir)
      CONFIG_DIR="${2:-}"
      shift 2
      ;;
    --no-dns)
      NO_DNS="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(id -u)" != "0" ]]; then
  echo "Run this installer with sudo/root." >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux client auto-install supports Linux only." >&2
  exit 1
fi

if [[ -z "$SERVER_HOST" || -z "$TOKEN" || -z "$CERT_FINGERPRINT" ]]; then
  echo "--server-host, --token, and --cert-fingerprint are required." >&2
  usage >&2
  exit 2
fi

validate_env_value() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._:@%+=,/-]+$ ]]; then
    echo "$name contains unsupported characters for /etc/pyvpn/client.env: $value" >&2
    exit 2
  fi
}

validate_env_value "server host" "$SERVER_HOST"
validate_env_value "token" "$TOKEN"
validate_env_value "certificate fingerprint" "$CERT_FINGERPRINT"
validate_env_value "control port" "$CONTROL_PORT"
validate_env_value "install dir" "$INSTALL_DIR"
validate_env_value "config dir" "$CONFIG_DIR"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "Could not find pyproject.toml. Run this from a pyvpn git checkout." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install python3 and python3-venv first." >&2
  exit 1
fi

if [[ ! -e /dev/net/tun ]]; then
  if command -v modprobe >/dev/null 2>&1; then
    modprobe tun || true
  fi
fi

if [[ ! -e /dev/net/tun ]]; then
  echo "/dev/net/tun is missing. Enable the Linux TUN driver on this client." >&2
  echo "On a VM/VPS, try: sudo modprobe tun" >&2
  echo "In a container, start it with /dev/net/tun and NET_ADMIN access." >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR"
if ! python3 -m venv "$INSTALL_DIR/venv"; then
  echo "Could not create a virtualenv. On Debian/Ubuntu, install python3-venv first." >&2
  exit 1
fi
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/venv/bin/python" -m pip install "$REPO_ROOT[linux]"

cat > "$CONFIG_DIR/client.env" <<EOF
PYVPN_SERVER_HOST=$SERVER_HOST
PYVPN_CONTROL_PORT=$CONTROL_PORT
PYVPN_TOKEN=$TOKEN
PYVPN_CERT_FINGERPRINT=$CERT_FINGERPRINT
PYVPN_TUN=pyvpn0
PYVPN_MTU=1280
PYVPN_NO_DNS=$NO_DNS
EOF
chmod 600 "$CONFIG_DIR/client.env"

cat > /usr/local/bin/pyvpn-client-start <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$CONFIG_DIR/client.env"
ARGS=(
  --server-host "\$PYVPN_SERVER_HOST"
  --control-port "\$PYVPN_CONTROL_PORT"
  --cert-fingerprint "\$PYVPN_CERT_FINGERPRINT"
  --tun "\$PYVPN_TUN"
  --mtu "\$PYVPN_MTU"
)
if [[ "\${PYVPN_NO_DNS:-0}" == "1" ]]; then
  ARGS+=(--no-dns)
fi
exec env PYVPN_TOKEN="\$PYVPN_TOKEN" "$INSTALL_DIR/venv/bin/pyvpn-client" "\${ARGS[@]}"
EOF
chmod 755 /usr/local/bin/pyvpn-client-start

cat <<EOF

pyvpn Linux client installed.

Connect:
  sudo pyvpn-client-start

Disconnect:
  Press Ctrl-C in the client terminal. The client restores routes and DNS on exit.

EOF
