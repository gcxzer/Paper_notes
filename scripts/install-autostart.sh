#!/usr/bin/env bash
set -euo pipefail

LABEL="${LABEL:-com.paper-notes.local}"
SERVICE_NAME="${SERVICE_NAME:-paper-notes.service}"
PORT="${PORT:-8765}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"
NPM_BIN="${NPM_BIN:-$(command -v npm || true)}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
LOG_DIR="$APP_DIR/tmp"
SKIP_NPM_INSTALL="${SKIP_NPM_INSTALL:-0}"

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "Could not find uv. Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

resolve_python_bin() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    printf '%s\n' "$VENV_DIR/bin/python"
    return 0
  fi
  if [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
    printf '%s\n' "$VENV_DIR/Scripts/python.exe"
    return 0
  fi
  return 1
}

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  printf '%s' "$value"
}

systemd_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

usage() {
  cat <<USAGE
Usage: scripts/install-autostart.sh

Environment overrides:
  LABEL               macOS launchd label (default: com.paper-notes.local)
  SERVICE_NAME        Linux systemd user service name (default: paper-notes.service)
  PORT                Local server port (default: 8765)
  UV_BIN              Path to uv
  NPM_BIN             Path to npm
  VENV_DIR            Python virtual environment path (default: .venv)
  SKIP_NPM_INSTALL=1  Skip automatic npm install for frontend dependencies
USAGE
}

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

prepare_python_environment() {
  echo "Preparing Paper Notes Python environment in $VENV_DIR"
  (
    cd "$APP_DIR"
    UV_PROJECT_ENVIRONMENT="$VENV_DIR" "$UV_BIN" sync
  )
  PYTHON_BIN="$(resolve_python_bin)" || {
    echo "uv sync finished, but no Python executable was found in $VENV_DIR." >&2
    exit 1
  }
}

prepare_frontend_environment() {
  if [[ "$SKIP_NPM_INSTALL" == "1" ]]; then
    echo "Skipping frontend dependency install because SKIP_NPM_INSTALL=1."
    return 0
  fi
  local missing_frontend_packages=()
  for package in pdfjs-dist katex lucide-static; do
    if [[ ! -d "$APP_DIR/node_modules/$package" ]]; then
      missing_frontend_packages+=("$package")
    fi
  done
  if [[ "${#missing_frontend_packages[@]}" -eq 0 ]]; then
    return 0
  fi
  if [[ -z "$NPM_BIN" || ! -x "$NPM_BIN" ]]; then
    echo "Could not find npm, and frontend dependencies are missing: ${missing_frontend_packages[*]}." >&2
    echo "Install Node.js/npm first, then run: npm install" >&2
    exit 1
  fi
  echo "Installing Paper Notes frontend dependencies with npm"
  (
    cd "$APP_DIR"
    "$NPM_BIN" install
  )
}

check_port_available() {
  "$PYTHON_BIN" - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

wait_for_port_available() {
  local attempts="${1:-20}"
  local index
  for ((index = 0; index < attempts; index += 1)); do
    if check_port_available; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

print_port_in_use_help() {
  echo "Port $PORT is already in use." >&2
  echo "Stop the existing Paper Notes server first, then run this again." >&2
  if command -v lsof >/dev/null 2>&1; then
    echo "To inspect the process, run: lsof -nP -iTCP:$PORT -sTCP:LISTEN" >&2
  elif command -v ss >/dev/null 2>&1; then
    echo "To inspect the process, run: ss -ltnp 'sport = :$PORT'" >&2
  fi
}

install_macos_launch_agent() {
  local launch_agents_dir="$HOME/Library/LaunchAgents"
  local plist_path="$launch_agents_dir/$LABEL.plist"

  mkdir -p "$launch_agents_dir"
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true

  if ! wait_for_port_available; then
    print_port_in_use_help
    exit 1
  fi

  local python_xml main_xml app_xml port_xml venv_xml stdout_xml stderr_xml
  python_xml="$(xml_escape "$PYTHON_BIN")"
  main_xml="$(xml_escape "$APP_DIR/main.py")"
  app_xml="$(xml_escape "$APP_DIR")"
  port_xml="$(xml_escape "$PORT")"
  venv_xml="$(xml_escape "$VENV_DIR")"
  stdout_xml="$(xml_escape "$LOG_DIR/paper-notes.launchd.out.log")"
  stderr_xml="$(xml_escape "$LOG_DIR/paper-notes.launchd.err.log")"

  cat > "$plist_path" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$python_xml</string>
    <string>$main_xml</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$app_xml</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PORT</key>
    <string>$port_xml</string>
    <key>UV_PROJECT_ENVIRONMENT</key>
    <string>$venv_xml</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$stdout_xml</string>
  <key>StandardErrorPath</key>
  <string>$stderr_xml</string>
</dict>
</plist>
PLIST

  launchctl bootstrap "gui/$(id -u)" "$plist_path"
  launchctl kickstart -k "gui/$(id -u)/$LABEL"

  echo "Paper Notes launchd service installed."
}

install_linux_systemd_user_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl was not found. The Python environment is ready, but autostart was not installed." >&2
    echo "Start Paper Notes manually with: PORT=$PORT \"$PYTHON_BIN\" \"$APP_DIR/main.py\"" >&2
    return 0
  fi
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "systemd user services are not available in this shell." >&2
    echo "The Python environment is ready, but autostart was not installed." >&2
    echo "Start Paper Notes manually with: PORT=$PORT \"$PYTHON_BIN\" \"$APP_DIR/main.py\"" >&2
    return 0
  fi

  local systemd_user_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  local service_path="$systemd_user_dir/$SERVICE_NAME"

  mkdir -p "$systemd_user_dir"
  systemctl --user stop "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl --user disable "$SERVICE_NAME" >/dev/null 2>&1 || true

  if ! wait_for_port_available; then
    print_port_in_use_help
    exit 1
  fi

  cat > "$service_path" <<SERVICE
[Unit]
Description=Paper Notes local service
After=network.target

[Service]
Type=simple
WorkingDirectory=$(systemd_quote "$APP_DIR")
Environment=$(systemd_quote "PORT=$PORT")
Environment=$(systemd_quote "UV_PROJECT_ENVIRONMENT=$VENV_DIR")
Environment=$(systemd_quote "PYTHONUNBUFFERED=1")
ExecStart=$(systemd_quote "$PYTHON_BIN") $(systemd_quote "$APP_DIR/main.py")
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
SERVICE

  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE_NAME"

  echo "Paper Notes systemd user service installed."
}

prepare_frontend_environment
prepare_python_environment

case "$(uname -s)" in
  Darwin)
    install_macos_launch_agent
    ;;
  Linux)
    install_linux_systemd_user_service
    ;;
  *)
    echo "Unsupported autostart platform: $(uname -s)." >&2
    echo "The Python environment is ready, but autostart was not installed." >&2
    echo "Start Paper Notes manually with: PORT=$PORT \"$PYTHON_BIN\" \"$APP_DIR/main.py\"" >&2
    ;;
esac

echo "Python: $PYTHON_BIN"
echo "Bookmark: http://127.0.0.1:$PORT"
