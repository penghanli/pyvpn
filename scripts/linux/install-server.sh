#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/linux/install-server.sh --public-host <server-ip-or-domain> [options]

Options:
  --public-host HOST       Public IP or DNS name clients should connect to. Required.
  --token TOKEN            Existing shared token. Defaults to a generated token.
  --control-port PORT      TLS control port. Default: 8443.
  --udp-port PORT          UDP tunnel port. Default: 8444.
  --dns IP                 DNS server pushed to clients. Default: 1.1.1.1.
  --install-dir DIR        Virtualenv install directory. Default: /opt/pyvpn.
  --config-dir DIR         Runtime config directory. Default: /etc/pyvpn.
  --force-cert             Regenerate server certificate even when one exists.

After installation:
  pyvpn-server-status
  pyvpn-server-restart
  pyvpn-server-logs
EOF
}

PUBLIC_HOST=""
TOKEN=""
CONTROL_PORT="8443"
UDP_PORT="8444"
DNS="1.1.1.1"
INSTALL_DIR="/opt/pyvpn"
CONFIG_DIR="/etc/pyvpn"
FORCE_CERT="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-host)
      PUBLIC_HOST="${2:-}"
      shift 2
      ;;
    --token)
      TOKEN="${2:-}"
      shift 2
      ;;
    --control-port)
      CONTROL_PORT="${2:-}"
      shift 2
      ;;
    --udp-port)
      UDP_PORT="${2:-}"
      shift 2
      ;;
    --dns)
      DNS="${2:-}"
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
    --force-cert)
      FORCE_CERT="1"
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
  echo "Server auto-install currently supports Linux only." >&2
  exit 1
fi

if [[ -z "$PUBLIC_HOST" ]]; then
  echo "--public-host is required. Use the VPS public IP or DNS name." >&2
  usage >&2
  exit 2
fi

validate_env_value() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9._:@%+=,/-]+$ ]]; then
    echo "$name contains unsupported characters for /etc/pyvpn/server.env: $value" >&2
    exit 2
  fi
}

validate_env_value "public host" "$PUBLIC_HOST"
validate_env_value "control port" "$CONTROL_PORT"
validate_env_value "UDP port" "$UDP_PORT"
validate_env_value "DNS" "$DNS"
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
  echo "/dev/net/tun is missing. Enable the Linux TUN driver on this server." >&2
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

if [[ -z "$TOKEN" ]]; then
  TOKEN="$("$INSTALL_DIR/venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
validate_env_value "token" "$TOKEN"

CERT_PATH="$CONFIG_DIR/server.crt"
KEY_PATH="$CONFIG_DIR/server.key"
FINGERPRINT_PATH="$CONFIG_DIR/server.fingerprint"

if [[ "$FORCE_CERT" == "1" || ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  "$INSTALL_DIR/venv/bin/pyvpn-cert" \
    --cert "$CERT_PATH" \
    --key "$KEY_PATH" \
    --common-name "$PUBLIC_HOST" \
    | tee "$FINGERPRINT_PATH"
  chmod 600 "$KEY_PATH"
fi

"$INSTALL_DIR/venv/bin/python" - "$CERT_PATH" > "$FINGERPRINT_PATH" <<'PY'
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pyvpn.auth import certificate_fingerprint

cert = x509.load_pem_x509_certificate(Path(sys.argv[1]).read_bytes())
print("certificate fingerprint: " + certificate_fingerprint(cert.public_bytes(serialization.Encoding.DER)))
PY

cat > "$CONFIG_DIR/server.env" <<EOF
PYVPN_TOKEN=$TOKEN
PYVPN_LISTEN_HOST=0.0.0.0
PYVPN_CONTROL_PORT=$CONTROL_PORT
PYVPN_UDP_PORT=$UDP_PORT
PYVPN_PUBLIC_HOST=$PUBLIC_HOST
PYVPN_CERT=$CERT_PATH
PYVPN_KEY=$KEY_PATH
PYVPN_TUN=pyvpn0
PYVPN_SUBNET=10.8.0.0/24
PYVPN_SERVER_VIP=10.8.0.1
PYVPN_CLIENT_VIP=10.8.0.2
PYVPN_DNS=$DNS
PYVPN_MTU=1280
PYVPN_SESSION_TIMEOUT=60
EOF
chmod 600 "$CONFIG_DIR/server.env"

cat > /etc/systemd/system/pyvpn-server.service <<EOF
[Unit]
Description=pyvpn server
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
EnvironmentFile=$CONFIG_DIR/server.env
ExecStart=$INSTALL_DIR/venv/bin/pyvpn-server --listen-host \${PYVPN_LISTEN_HOST} --control-port \${PYVPN_CONTROL_PORT} --udp-port \${PYVPN_UDP_PORT} --public-host \${PYVPN_PUBLIC_HOST} --cert \${PYVPN_CERT} --key \${PYVPN_KEY} --tun \${PYVPN_TUN} --subnet \${PYVPN_SUBNET} --server-vip \${PYVPN_SERVER_VIP} --client-vip \${PYVPN_CLIENT_VIP} --dns \${PYVPN_DNS} --mtu \${PYVPN_MTU} --session-timeout \${PYVPN_SESSION_TIMEOUT}
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pyvpn-server

cat > /usr/local/bin/pyvpn-server-restart <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl restart pyvpn-server.service
state="$(systemctl is-active pyvpn-server.service || true)"
if [[ "$state" == "active" ]]; then
  echo "pyvpn server restarted successfully."
  systemctl --no-pager --full status pyvpn-server.service
else
  echo "pyvpn server restart finished, but service state is: $state" >&2
  systemctl --no-pager --full status pyvpn-server.service || true
  exit 1
fi
EOF
chmod 755 /usr/local/bin/pyvpn-server-restart

cat > /usr/local/bin/pyvpn-server-status <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
systemctl --no-pager --full status pyvpn-server.service
EOF
chmod 755 /usr/local/bin/pyvpn-server-status

cat > /usr/local/bin/pyvpn-server-logs <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
journalctl -u pyvpn-server.service -f
EOF
chmod 755 /usr/local/bin/pyvpn-server-logs

FINGERPRINT="$(sed -n 's/^certificate fingerprint: //p' "$FINGERPRINT_PATH")"

cat <<EOF

pyvpn server installed and started.

Server commands:
  sudo pyvpn-server-status
  sudo pyvpn-server-logs
  sudo pyvpn-server-restart

Open these firewall ports on the VPS:
  TCP $CONTROL_PORT
  UDP $UDP_PORT

Client settings:
  server host: $PUBLIC_HOST
  control port: $CONTROL_PORT
  token: $TOKEN
  cert fingerprint: $FINGERPRINT

EOF
