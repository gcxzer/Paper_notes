#!/bin/zsh
cd "$(dirname "$0")"
uv run uvicorn paper_notes_server.main:app --host 127.0.0.1 --port "${PORT:-4173}" &
sleep 1
open "http://localhost:${PORT:-4173}"
