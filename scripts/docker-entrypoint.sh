#!/usr/bin/env sh
set -eu

APP_ROOT="${APP_ROOT:-/app}"

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

exec "$@"
