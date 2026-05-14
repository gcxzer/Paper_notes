#!/usr/bin/env bash
set -euo pipefail

LABEL="${LABEL:-com.paper-notes.local}"
SERVICE_NAME="${SERVICE_NAME:-paper-notes.service}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
REMOVE_VENV="${REMOVE_VENV:-0}"

usage() {
  cat <<USAGE
Usage: scripts/uninstall-autostart.sh [--remove-venv]

Options:
  --remove-venv  Also delete the project Python virtual environment
  -h, --help     Show this help

Environment overrides:
  LABEL         macOS launchd label (default: com.paper-notes.local)
  SERVICE_NAME  Linux systemd user service name (default: paper-notes.service)
  VENV_DIR      Python virtual environment path (default: .venv)
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --remove-venv)
      REMOVE_VENV=1
      ;;
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

uninstall_macos_launch_agent() {
  local plist_path="$HOME/Library/LaunchAgents/$LABEL.plist"
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
  rm -f "$plist_path"
  echo "Paper Notes launchd service removed."
}

uninstall_linux_systemd_user_service() {
  local systemd_user_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  local service_path="$systemd_user_dir/$SERVICE_NAME"

  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    rm -f "$service_path"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo "Paper Notes systemd user service removed."
  else
    rm -f "$service_path"
    echo "systemd user services are not available; removed the service file if it existed."
  fi
}

case "$(uname -s)" in
  Darwin)
    uninstall_macos_launch_agent
    ;;
  Linux)
    uninstall_linux_systemd_user_service
    ;;
  *)
    echo "Unsupported autostart platform: $(uname -s)."
    ;;
esac

if [[ "$REMOVE_VENV" == "1" ]]; then
  rm -rf "$VENV_DIR"
  echo "Removed Python environment: $VENV_DIR"
else
  echo "Kept Python environment: $VENV_DIR"
  echo "Run $0 --remove-venv to remove it."
fi
