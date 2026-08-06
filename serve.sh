#!/usr/bin/env bash
# Keep the whisper model resident. Cuts transcription from ~500ms to ~150ms
# by avoiding a model load per utterance, and avoids the 11-13s Metal shader
# compile that a cold whisper-cli can hit.
set -euo pipefail
cd "$(dirname "$0")"

MODEL=$(uv run python -c "import config; print(config.load().model)")
echo "serving $MODEL on :8178"

exec whisper-server \
  -m "$MODEL" \
  --host 127.0.0.1 \
  --port 8178
