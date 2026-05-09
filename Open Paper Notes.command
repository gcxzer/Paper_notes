#!/bin/zsh
cd "$(dirname "$0")"
npm start &
sleep 1
open "http://localhost:4173"
