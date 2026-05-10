#!/usr/bin/env bash
# Pulls the Ollama models needed by the AI service.
# Run this AFTER `docker compose up -d ollama` and BEFORE the first time
# you start ai-service. Models are stored in the `ollama-data` volume
# and persist across container restarts.

set -euo pipefail

echo "Pulling embedding model: nomic-embed-text (~ 274MB)..."
docker compose exec -T ollama ollama pull nomic-embed-text

echo "Pulling LLM: llama3.2:3b (~ 2.0GB)..."
docker compose exec -T ollama ollama pull llama3.2:3b

echo "Done. Available models:"
docker compose exec -T ollama ollama list
