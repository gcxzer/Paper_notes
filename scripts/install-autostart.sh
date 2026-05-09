#!/bin/zsh
set -euo pipefail

LABEL="com.paper-notes.local"
PORT="${PORT:-4173}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV_BIN="${UV_BIN:-$(command -v uv)}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
LOG_DIR="$APP_DIR/tmp"

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "Could not find uv. Install uv first." >&2
  exit 1
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already in use." >&2
  echo "Stop the existing server first, then run this again:" >&2
  echo "  Ctrl-C in the uvicorn terminal" >&2
  exit 1
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd "$APP_DIR" &amp;&amp; exec "$UV_BIN" run uvicorn paper_notes_server.main:app --host 127.0.0.1 --port "$PORT"</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$APP_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PORT</key>
    <string>$PORT</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/paper-notes.launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/paper-notes.launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Paper Notes will auto-start at login."
echo "Bookmark: http://127.0.0.1:$PORT"
