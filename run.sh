#!/usr/bin/env bash
# Start the model server (if not already up) and the dictation daemon.
set -euo pipefail
cd "$(dirname "$0")"

if ! pgrep -f "whisper-server.*8178" >/dev/null; then
  echo "starting whisper-server..."
  nohup ./serve.sh > .scratch/server.log 2>&1 &
  for _ in $(seq 1 40); do
    nc -z 127.0.0.1 8178 2>/dev/null && break
    sleep 0.25
  done
fi

exec uv run kyanth.py "$@"
