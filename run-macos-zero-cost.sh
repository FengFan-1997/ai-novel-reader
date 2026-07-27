#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
  echo "Environment not found. Run ./setup-macos-zero-cost.sh first."
  exit 1
fi
curl --silent --fail http://localhost:11434/api/tags >/dev/null || brew services start ollama
export TTS_STORY_PORT="${TTS_STORY_PORT:-7860}"

bridge_url_available=false
bridge_secret_available=false
if command -v security >/dev/null 2>&1; then
  security find-generic-password -s "ShengYue Cloud Bridge URL" -w >/dev/null 2>&1 && bridge_url_available=true
  security find-generic-password -s "ShengYue Cloud Bridge Secret" -w >/dev/null 2>&1 && bridge_secret_available=true
fi
if [[ -n "${SHENGYUE_CLOUD_RELAY_URL:-}" ]]; then
  bridge_url_available=true
fi
if [[ -n "${SHENGYUE_CLOUD_BRIDGE_SECRET:-}" ]]; then
  bridge_secret_available=true
fi

if [[ "$bridge_url_available" != true || "$bridge_secret_available" != true ]]; then
  exec .venv/bin/python app.py
fi

.venv/bin/python app.py &
app_pid=$!
cleanup() {
  kill "$app_pid" >/dev/null 2>&1 || true
  wait "$app_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

for _ in {1..90}; do
  if curl --silent --fail "http://127.0.0.1:${TTS_STORY_PORT}/api/health" >/dev/null; then
    break
  fi
  if ! kill -0 "$app_pid" >/dev/null 2>&1; then
    wait "$app_pid"
    exit $?
  fi
  sleep 1
done

export SHENGYUE_LOCAL_URL="http://127.0.0.1:${TTS_STORY_PORT}"
.venv/bin/python -m src.cloud_bridge
