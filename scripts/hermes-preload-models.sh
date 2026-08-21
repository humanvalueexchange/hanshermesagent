#!/usr/bin/env bash
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
KEEP_ALIVE="${KEEP_ALIVE:--1}"
PRIMARY_MODEL="qwen3.8:27b"
DERIVER_MODEL="qwen2.5:3b"
EMBEDDING_MODEL="nomic-embed-text"

log() {
  echo "[preload] $*"
}

wait_for_ollama() {
  local retries=90
  while ! curl --fail --silent "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; do
    sleep 2
    retries=$((retries - 1))
    if [ "${retries}" -le 0 ]; then
      log "ERROR: Ollama not ready after 180 seconds"
      exit 1
    fi
  done
}

load_generate_model() {
  local model="$1"
  local context="$2"
  log "Loading ${model}"
  curl --fail --silent --show-error --max-time 300 "${OLLAMA_URL}/api/generate" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${model}\",\"prompt\":\"ok\",\"keep_alive\":${KEEP_ALIVE},\"stream\":false,\"options\":{\"num_ctx\":${context}}}" \
    >/dev/null
}

load_embedding_model() {
  log "Loading ${EMBEDDING_MODEL}"
  curl --fail --silent --show-error --max-time 120 "${OLLAMA_URL}/api/embed" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"${EMBEDDING_MODEL}\",\"input\":\"Hermes embedding warmup\",\"keep_alive\":${KEEP_ALIVE}}" \
    >/dev/null
}

wait_for_ollama
load_generate_model "${PRIMARY_MODEL}" 131072
load_generate_model "${DERIVER_MODEL}" 32768
load_embedding_model
log "Done. Hot policy: ${PRIMARY_MODEL}, ${DERIVER_MODEL}, and ${EMBEDDING_MODEL}."
