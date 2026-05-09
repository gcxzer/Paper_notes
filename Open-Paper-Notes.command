#!/bin/zsh
cd "$(dirname "$0")"
uv run python main.py &
sleep 1
open "http://localhost:4173"
