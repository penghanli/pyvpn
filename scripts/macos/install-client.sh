#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/macos/install-client.sh \
    --server-host <server-ip-or-domain> \
    --token <shared-token> \
    --cert-fingerprint 'sha256:<fingerprint>'

Options:
  --server-host HOST        Server public IP or DNS name. Required.
  --token TOKEN             Shared token printed by install-server.sh. Required.
  --cert-fingerprint FP     Server certificate fingerprint. Required.
  --control-port PORT       TLS control port. Default: 8443.
  --bypass-ip IP            Extra IP to keep outside the VPN. Repeatable.
  --tun NAME                utun interface to request. Default: utun7.
  --install-dir DIR         Virtualenv install directory. Default: /opt/pyvpn-client.
  --config-dir DIR          Runtime config directory. Default: /Library/Application Support/pyvpn.
  --run-dir DIR             PID/stop-file directory. Default: /var/run/pyvpn.
  --log-dir DIR             Log directory. Default: /var/log/pyvpn.
  --no-dns                  Do not change client DNS while connected.

After installation:
  sudo pyvpn-client-up
  sudo pyvpn-client-down
  sudo pyvpn-client-status
EOF
}

SERVER_HOST=""
TOKEN=""
CERT_FINGERPRINT=""
CONTROL_PORT="8443"
TUN_NAME="utun7"
INSTALL_DIR="/opt/pyvpn-client"
CONFIG_DIR="/Library/Application Support/pyvpn"
RUN_DIR="/var/run/pyvpn"
LOG_DIR="/var/log/pyvpn"
NO_DNS="0"
BYPASS_IPS_CSV=""

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
    --bypass-ip)
      if [[ -n "$BYPASS_IPS_CSV" ]]; then
        BYPASS_IPS_CSV="$BYPASS_IPS_CSV,${2:-}"
      else
        BYPASS_IPS_CSV="${2:-}"
      fi
      shift 2
      ;;
    --tun)
      TUN_NAME="${2:-}"
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
    --run-dir)
      RUN_DIR="${2:-}"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="${2:-}"
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

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS client auto-install supports macOS only." >&2
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
    echo "$name contains unsupported characters for client.env: $value" >&2
    exit 2
  fi
}

validate_env_value "server host" "$SERVER_HOST"
validate_env_value "token" "$TOKEN"
validate_env_value "certificate fingerprint" "$CERT_FINGERPRINT"
validate_env_value "control port" "$CONTROL_PORT"
validate_env_value "tun name" "$TUN_NAME"

if [[ -n "${SSH_CLIENT:-}" ]]; then
  if [[ -n "$BYPASS_IPS_CSV" ]]; then
    BYPASS_IPS_CSV="$BYPASS_IPS_CSV,${SSH_CLIENT%% *}"
  else
    BYPASS_IPS_CSV="${SSH_CLIENT%% *}"
  fi
fi

if [[ -n "$BYPASS_IPS_CSV" ]]; then
  OLD_IFS="$IFS"
  IFS=","
  for bypass_ip in $BYPASS_IPS_CSV; do
    validate_env_value "bypass IP" "$bypass_ip"
  done
  IFS="$OLD_IFS"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "Could not find pyproject.toml. Run this from a pyvpn git checkout." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 3.9+ is required. Install Python 3 first, for example: brew install python" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$CONFIG_DIR" "$RUN_DIR" "$LOG_DIR" /usr/local/bin
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/venv/bin/python" -m pip install "$REPO_ROOT"

cat > "$CONFIG_DIR/client.env" <<EOF
PYVPN_SERVER_HOST=$SERVER_HOST
PYVPN_CONTROL_PORT=$CONTROL_PORT
PYVPN_TOKEN=$TOKEN
PYVPN_CERT_FINGERPRINT=$CERT_FINGERPRINT
PYVPN_TUN=$TUN_NAME
PYVPN_MTU=1280
PYVPN_NO_DNS=$NO_DNS
PYVPN_BYPASS_IPS=$BYPASS_IPS_CSV
EOF
chmod 600 "$CONFIG_DIR/client.env"

cat > /usr/local/bin/pyvpn-client-start <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$CONFIG_DIR/client.env"
RUN_DIR="$RUN_DIR"
STOP_FILE="\$RUN_DIR/client.stop"
mkdir -p "\$RUN_DIR"
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
  for ip in "\${SAVED_BYPASS_IPS[@]}"; do
    add_bypass_ip "\$ip"
  done
fi

if [[ -n "\${SSH_CLIENT:-}" ]]; then
  add_bypass_ip "\${SSH_CLIENT%% *}"
fi

if [[ "\${PYVPN_NO_DNS:-0}" == "1" ]]; then
  ARGS+=(--no-dns)
fi

exec env PYVPN_TOKEN="\$PYVPN_TOKEN" "$INSTALL_DIR/venv/bin/pyvpn-client" "\${ARGS[@]}"
EOF
chmod 755 /usr/local/bin/pyvpn-client-start

cat > /usr/local/bin/pyvpn-client-up <<EOF
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$RUN_DIR"
LOG_DIR="$LOG_DIR"
PID_FILE="\$RUN_DIR/client.pid"
STOP_FILE="\$RUN_DIR/client.stop"
LOG_FILE="\$LOG_DIR/client.log"
ERR_FILE="\$LOG_DIR/client.err.log"
mkdir -p "\$RUN_DIR" "\$LOG_DIR"

if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
  if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
    echo "pyvpn client is already running with PID \$PID"
    echo "Log: \$LOG_FILE"
    echo "Error log: \$ERR_FILE"
    exit 0
  fi
fi

rm -f "\$STOP_FILE" "\$PID_FILE"
nohup /usr/local/bin/pyvpn-client-start >"\$LOG_FILE" 2>"\$ERR_FILE" &
PID="\$!"
echo "\$PID" > "\$PID_FILE"
sleep 2

if ! kill -0 "\$PID" >/dev/null 2>&1; then
  if [[ -f "\$LOG_FILE" ]]; then tail -n 80 "\$LOG_FILE"; fi
  if [[ -f "\$ERR_FILE" ]]; then tail -n 80 "\$ERR_FILE"; fi
  rm -f "\$PID_FILE"
  echo "pyvpn client failed to start" >&2
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
CONFIG_DIR="$CONFIG_DIR"
RUN_DIR="$RUN_DIR"
PID_FILE="\$RUN_DIR/client.pid"
STOP_FILE="\$RUN_DIR/client.stop"
DNS_STATE="\$RUN_DIR/macos-dns-state.json"

if [[ -f "\$PID_FILE" ]]; then
  PID="\$(cat "\$PID_FILE")"
else
  PID=""
fi

if [[ -n "\$PID" ]] && kill -0 "\$PID" >/dev/null 2>&1; then
  touch "\$STOP_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "\$PID" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if kill -0 "\$PID" >/dev/null 2>&1; then
    kill "\$PID" >/dev/null 2>&1 || true
    sleep 2
  fi
  if kill -0 "\$PID" >/dev/null 2>&1; then
    kill -9 "\$PID" >/dev/null 2>&1 || true
  fi
  echo "pyvpn client stopped"
else
  echo "pyvpn client is not running"
fi

rm -f "\$PID_FILE" "\$STOP_FILE"
route -n delete -net 0.0.0.0 -netmask 128.0.0.0 >/dev/null 2>&1 || true
route -n delete -net 128.0.0.0 -netmask 128.0.0.0 >/dev/null 2>&1 || true

if [[ -f "\$CONFIG_DIR/client.env" ]]; then
  source "\$CONFIG_DIR/client.env"
  route -n delete -host "\$PYVPN_SERVER_HOST" >/dev/null 2>&1 || true
  if command -v python3 >/dev/null 2>&1; then
    SERVER_IP="\$(python3 -c 'import socket, sys; print(socket.gethostbyname(sys.argv[1]))' "\$PYVPN_SERVER_HOST" 2>/dev/null || true)"
    if [[ -n "\$SERVER_IP" ]]; then
      route -n delete -host "\$SERVER_IP" >/dev/null 2>&1 || true
    fi
  fi
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - "\$DNS_STATE" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
if state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        service = str(state.get("service") or "")
        dns = state.get("dns")
        if service:
            servers = [str(item) for item in dns] if isinstance(dns, list) and dns else ["Empty"]
            subprocess.run(["networksetup", "-setdnsservers", service, *servers], check=False)
    except Exception:
        pass
    try:
        state_path.unlink()
    except OSError:
        pass
PY
fi
EOF
chmod 755 /usr/local/bin/pyvpn-client-down

cat > /usr/local/bin/pyvpn-client-status <<EOF
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$RUN_DIR"
LOG_DIR="$LOG_DIR"
PID_FILE="\$RUN_DIR/client.pid"
LOG_FILE="\$LOG_DIR/client.log"
ERR_FILE="\$LOG_DIR/client.err.log"

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
if [[ -f "\$ERR_FILE" ]]; then tail -n 40 "\$ERR_FILE"; fi
EOF
chmod 755 /usr/local/bin/pyvpn-client-status

cat <<EOF

pyvpn macOS client installed.

Connect in the background:
  sudo pyvpn-client-up

Disconnect:
  sudo pyvpn-client-down

Status and logs:
  sudo pyvpn-client-status
  sudo tail -f "$LOG_DIR/client.log" "$LOG_DIR/client.err.log"

Foreground debug mode:
  sudo pyvpn-client-start

EOF
