#!/bin/zsh
cd "$(dirname "$0")"
uv run python src/paper_notes/server.py &
sleep 1
open "http://localhost:4173"
