#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This installer is for Apple Silicon Macs."
  exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh"
  exit 1
fi
HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.12 ollama ffmpeg
python_bin="$(brew --prefix python@3.12)/bin/python3.12"
"$python_bin" -m venv .venv
.venv/bin/python -m pip install -r requirements-macos-zero-cost.txt
.venv/bin/python -m pip install uv

index_tts_dir="$project_dir/engines/index-tts"
if [[ ! -f "$index_tts_dir/pyproject.toml" ]]; then
  index_tts_source="$(mktemp -d)"
  cleanup_index_source() {
    rm -rf "$index_tts_source"
  }
  trap cleanup_index_source EXIT
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 \
    https://github.com/index-tts/index-tts.git "$index_tts_source"
  mkdir -p "$index_tts_dir"
  rsync -a --exclude=".git" --exclude="tts_worker.py" \
    "$index_tts_source/" "$index_tts_dir/"
  cleanup_index_source
  trap - EXIT
fi
(
  cd "$index_tts_dir"
  ../../.venv/bin/uv sync --no-dev
)

brew services start ollama
for _ in {1..30}; do
  curl --silent --fail http://localhost:11434/api/tags >/dev/null && break
  sleep 1
done
curl --silent --fail http://localhost:11434/api/tags >/dev/null || {
  echo "Ollama did not start. Run: brew services restart ollama"
  exit 1
}
ollama pull qwen3:1.7b
echo "Setup complete. Start with: ./run-macos-zero-cost.sh"
