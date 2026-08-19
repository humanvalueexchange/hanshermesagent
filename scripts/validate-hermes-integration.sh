#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${HVE_KNOWLEDGE_PYTHON:-/home/hans/.hve-knowledge/venv/bin/python3}"
PROFILE_NAME="$(cat "$HOME/.hermes/active_profile" 2>/dev/null || printf 'main')"
PROFILE="$HOME/.hermes/profiles/$PROFILE_NAME"
JOBS_FILE="$PROFILE/cron/jobs.json"
DATA_DIR="$HOME/freqtrade/user_data/data"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

pass() {
  printf 'PASS: %s\n' "$*"
}

[[ -x "$PYTHON_BIN" ]] || fail "knowledge Python is unavailable: $PYTHON_BIN"
command -v curl >/dev/null || fail "curl is required"
command -v jq >/dev/null || fail "jq is required"
command -v ollama >/dev/null || fail "ollama is required"

printf 'Running repository tests...\n'
(cd "$REPO_ROOT" && "$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py')
pass "repository test suite"

systemctl --user is-active --quiet hermes-mcp.service || fail "hermes-mcp.service is not active"
systemctl --user is-active --quiet hermes-gateway-hanshermesagent.service || fail "Hermes gateway is not active"
systemctl --user is-active --quiet hve-intake.path || fail "hve-intake.path is not active"
pass "Hermes gateway, MCP, and intake watcher are active"

health="$(curl -fsS --max-time 5 http://127.0.0.1:8765/health)" || fail "MCP health endpoint failed"
[[ "$(jq -r '.status' <<<"$health")" == "ok" ]] || fail "MCP health response is not ok"
pass "MCP health endpoint"

unit_environment="$(systemctl --user show hermes-mcp.service -p Environment --value)"
grep -Fq 'HVE_MCP_HOST=127.0.0.1' <<<"$unit_environment" ||
  fail "MCP is not explicitly bound to loopback"
[[ "$(stat -c '%a' "$HOME/.hermes-mcp.env" 2>/dev/null || true)" == "600" ]] ||
  fail "MCP environment file must have mode 600"
pass "MCP loopback binding and secret permissions"

command -v pdftotext >/dev/null || fail "pdftotext is unavailable"
command -v tesseract >/dev/null || fail "tesseract is unavailable"
pass "native PDF and OCR tools"

[[ -f "$JOBS_FILE" ]] || fail "Hermes cron jobs file is missing"
python3 - "$JOBS_FILE" <<'PY'
import json
import sys
from pathlib import Path

jobs = json.loads(Path(sys.argv[1]).read_text())["jobs"]
if not jobs:
    raise SystemExit("no cron jobs configured")
for job in jobs:
    if not job.get("enabled"):
        raise SystemExit(f"disabled cron job: {job.get('name')}")
    if not str(job.get("deliver", "")).startswith("whatsapp:"):
        raise SystemExit(f"cron job is not WhatsApp-delivered: {job.get('name')}")
PY
pass "cron jobs enabled and routed to WhatsApp"

python3 - "$REPO_ROOT/config/llm-stack.yaml" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

import yaml

manifest = yaml.safe_load(Path(sys.argv[1]).read_text())
resident = [entry["model"] for entry in manifest["resident"].values()]
installed = {
    line.split()[0]
    for line in subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True).stdout.splitlines()[1:]
    if line.strip()
}
missing = [model for model in resident if model not in installed and not any(model + ":" in item for item in installed)]
if missing:
    raise SystemExit("missing resident models: " + ", ".join(missing))
loaded = {
    line.split()[0]
    for line in subprocess.run(["ollama", "ps"], capture_output=True, text=True, check=True).stdout.splitlines()[1:]
    if line.strip()
}
not_loaded = [model for model in resident if model not in loaded and not any(model + ":" in item for item in loaded)]
if not_loaded:
    raise SystemExit("resident models not loaded: " + ", ".join(not_loaded))
PY
pass "resident Ollama models installed and loaded"

for timeframe in 1m 5m 15m 1h 4h 1d; do
  [[ -f "$DATA_DIR/BTC_USD-${timeframe}.feather" ]] || fail "missing Kraken data file: BTC_USD-${timeframe}.feather"
done
pass "Kraken BTC/USD data files"

printf 'INTEGRATION CHECK PASSED\n'
