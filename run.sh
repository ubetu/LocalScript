#!/usr/bin/env bash
set -euo pipefail

# Detect NVIDIA GPU
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
  echo "NVIDIA GPU detected. Starting with GPU support..."
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build "$@"
else
  echo "No NVIDIA GPU detected. Starting in CPU-only mode..."
  echo ""
  echo "NOTE: On macOS, Docker cannot access Apple Metal/MPS GPUs."
  echo "For better performance on Mac, run Ollama natively:"
  echo "  brew install ollama && ollama serve"
  echo "Then start only the app container:"
  echo "  OLLAMA_HOST=http://host.docker.internal:11434 docker compose up app --build"
  echo ""
  docker compose up --build "$@"
fi
