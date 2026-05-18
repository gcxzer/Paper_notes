#!/usr/bin/env sh
set -eu

APP_ROOT="${APP_ROOT:-/app}"
PAPER_NOTES_UID="${PAPER_NOTES_UID:-1000}"
PAPER_NOTES_GID="${PAPER_NOTES_GID:-1000}"

case "$PAPER_NOTES_UID" in
  *[!0-9]*|"") echo "PAPER_NOTES_UID must be a numeric user id." >&2; exit 1 ;;
esac

case "$PAPER_NOTES_GID" in
  *[!0-9]*|"") echo "PAPER_NOTES_GID must be a numeric group id." >&2; exit 1 ;;
esac

if [ -d "$APP_ROOT/notes.json" ]; then
  echo "$APP_ROOT/notes.json is a directory. Create notes.json as a file on the host before starting Docker." >&2
  exit 1
fi

mkdir -p \
  "$APP_ROOT/resources/Papers" \
  "$APP_ROOT/resources/Paper-html" \
  "$APP_ROOT/resources/Paper-annotations" \
  "$APP_ROOT/resources/Paper-text" \
  "$APP_ROOT/resources/Paper-pages" \
  "$APP_ROOT/resources/Paper-images" \
  "$APP_ROOT/.paper-notes/sessions" \
  "$APP_ROOT/.paper-notes/compression" \
  "$APP_ROOT/.paper-notes/snapshots" \
  "$APP_ROOT/.paper-notes/approvals" \
  "$APP_ROOT/.paper-notes/logs" \
  "$APP_ROOT/.paper-notes/memory" \
  "$APP_ROOT/.paper-notes/media" \
  "$APP_ROOT/.paper-notes/media/uploads" \
  "$APP_ROOT/.paper-notes/skills" \
  "$APP_ROOT/.paper-notes/auth" \
  "$APP_ROOT/tmp"

if [ ! -e "$APP_ROOT/notes.json" ] || [ ! -s "$APP_ROOT/notes.json" ]; then
  cat > "$APP_ROOT/notes.json" <<'JSON'
{
  "categories": [
    {
      "id": "all",
      "name": "All Notes",
      "parentId": null,
      "order": 0,
      "system": true
    },
    {
      "id": "uncategorized",
      "name": "Uncategorized",
      "parentId": null,
      "order": 1,
      "system": true
    }
  ],
  "notes": []
}
JSON
fi

if [ "$(id -u)" = "0" ]; then
  chown "$PAPER_NOTES_UID:$PAPER_NOTES_GID" "$APP_ROOT"
  chown -R "$PAPER_NOTES_UID:$PAPER_NOTES_GID" \
    "$APP_ROOT/resources" \
    "$APP_ROOT/.paper-notes" \
    "$APP_ROOT/tmp"
  chown "$PAPER_NOTES_UID:$PAPER_NOTES_GID" "$APP_ROOT/notes.json"

  export HOME="$APP_ROOT/.paper-notes"
  exec gosu "$PAPER_NOTES_UID:$PAPER_NOTES_GID" "$@"
fi

exec "$@"
