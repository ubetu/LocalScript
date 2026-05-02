#!/usr/bin/env bash
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
MODEL="${OLLAMA_MODEL:-qwen2.5-coder:7b-instruct-q6_K}"

# ── 1. Wait for Ollama to become reachable ────────────────────────────────────
echo "Waiting for Ollama at ${OLLAMA_HOST}..."
until curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; do
  sleep 2
done
echo "Ollama is ready."

# ── 2. Pull the model if it is not already available ──────────────────────────
if curl -sf "${OLLAMA_HOST}/api/tags" | grep -q "${MODEL}"; then
  echo "Model '${MODEL}' is already available."
else
  echo "====================================================="
  echo "  Pulling model '${MODEL}'"
  echo "  This may take a while on first run (~5 GB download)"
  echo "====================================================="
  curl -X POST "${OLLAMA_HOST}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${MODEL}\",\"stream\":false}"
  echo ""
  echo "Model '${MODEL}' pulled successfully."
fi

# ── 3. Start the application ──────────────────────────────────────────────────
echo "Starting LocalScript API..."
exec uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
