#!/usr/bin/env bash
# Verify that the live Hermes runtime matches the hermes-cfo repository contract.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVE_PROFILE="$(cat "$HOME/.hermes/active_profile" 2>/dev/null || printf 'main')"
PROFILE="${HERMES_PROFILE:-$HOME/.hermes/profiles/$ACTIVE_PROFILE}"
CODER_PROFILE="${HERMES_CODER_PROFILE:-$HOME/.hermes/profiles/hermes-coder}"
ENV_FILE="${HERMES_ENV_FILE:-$HOME/.hermes-mcp.env}"
UNIT_DIR="${HERMES_UNIT_DIR:-$HOME/.config/systemd/user}"
if [[ "$PROFILE" != /* ]]; then
  PROFILE="$HOME/.hermes/profiles/$PROFILE"
fi
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

errors=0
warn() {
  printf 'WARN %s\n' "$*"
}
fail() {
  printf 'FAIL %s\n' "$*"
  errors=$((errors + 1))
}
pass() {
  printf 'PASS %s\n' "$*"
}

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  fail "repository worktree is dirty; review or commit changes before deployment"
else
  pass "repository worktree is clean at $(git -C "$REPO_ROOT" rev-parse --short HEAD)"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  fail "runtime environment file is missing: $ENV_FILE"
else
  if grep -q '^HVE_MCP_API_KEY=' "$ENV_FILE" && \
     [[ "$(stat -c '%a' "$ENV_FILE")" == "600" ]]; then
    pass "runtime environment file exists with mode 600"
  else
    fail "runtime environment file must contain HVE_MCP_API_KEY and have mode 600"
  fi

  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
  [[ -n "${HVE_MCP_API_KEY:-}" ]] && pass "HVE_MCP_API_KEY is configured" || fail "HVE_MCP_API_KEY is empty"
fi

if [[ -f "$ENV_FILE" ]]; then
  rendered_config="$TMP_DIR/config.yaml"
  manifest="$REPO_ROOT/config/llm-stack.yaml"
  sed "s/\${HVE_MCP_API_KEY}/${HVE_MCP_API_KEY:-}/g" \
    "$REPO_ROOT/config/hermes-config.template.yaml" > "$rendered_config"
  if [[ ! -f "$REPO_ROOT/config/llm-stack.yaml" ]]; then
    fail "model stack manifest is missing: $REPO_ROOT/config/llm-stack.yaml"
  elif [[ ! -f "$PROFILE/config.yaml" ]]; then
    fail "live Hermes config is missing: $PROFILE/config.yaml"
  elif python3 - "$rendered_config" "$PROFILE/config.yaml" "$CODER_PROFILE/config.yaml" "$manifest" <<'PY'
import sys
from pathlib import Path

import yaml

template = yaml.safe_load(Path(sys.argv[1]).read_text())
live = yaml.safe_load(Path(sys.argv[2]).read_text())
coder = yaml.safe_load(Path(sys.argv[3]).read_text())
manifest = yaml.safe_load(Path(sys.argv[4]).read_text())

resident = manifest["resident"]
expected_models = {entry["model"] for entry in resident.values()}
primary = resident["primary"]["model"]
expected_contexts = {entry["model"]: entry["context"] for entry in resident.values()}
provider_config = next(iter((live.get("providers") or {}).values()), {})
coder_provider = next(iter((coder.get("providers") or {}).values()), {})

checks = [
    (live.get("model", {}).get("default") == primary, "primary model"),
    (live.get("model", {}).get("context_length") == expected_contexts[primary], "primary context length"),
    (live.get("model", {}).get("ollama_num_ctx") == expected_contexts[primary], "primary Ollama context override"),
    (provider_config.get("default_model") == primary, "provider default model"),
    (set(provider_config.get("models") or []) == expected_models, "approved Ollama model catalog"),
    (coder.get("model", {}).get("default") == primary, "Hermes-coder primary model"),
    (coder.get("model", {}).get("context_length") == expected_contexts[primary], "Hermes-coder context length"),
    (coder_provider.get("default_model") == primary, "Hermes-coder provider default model"),
    (set(coder_provider.get("models") or []) == expected_models, "Hermes-coder model catalog"),
    (live.get("memory", {}).get("provider") == "honcho", "Honcho memory provider"),
    (live.get("security", {}).get("allow_private_urls") is False, "private URL protection"),
    (live.get("security", {}).get("tirith_fail_open") is False, "Tirith fail-closed mode"),
]
failed = [label for ok, label in checks if not ok]
if failed:
    print("; ".join(failed))
    raise SystemExit(1)
PY
  then
    pass "active profile config satisfies the repository runtime contract: $PROFILE"
  else
    fail "active profile config violates the repository runtime contract: $PROFILE/config.yaml"
  fi
  if [[ ! -f "$CODER_PROFILE/config.yaml" ]]; then
    fail "Hermes-coder config is missing: $CODER_PROFILE/config.yaml"
  else
    pass "Hermes-coder config satisfies the repository runtime contract: $CODER_PROFILE/config.yaml"
  fi
else
  fail "cannot render live Hermes config without the environment file"
fi

cron_file="$HOME/.hermes/profiles/hanshermesagent/cron/jobs.json"
if [[ ! -f "$cron_file" ]]; then
  fail "Hermes cron configuration is missing: $cron_file"
elif python3 - "$cron_file" "$manifest" <<'PY'
import json
import sys
from pathlib import Path
import yaml

jobs = json.loads(Path(sys.argv[1]).read_text())["jobs"]
manifest = yaml.safe_load(Path(sys.argv[2]).read_text())
primary = manifest["resident"]["primary"]["model"]
obsolete = ("qwen3.5:27b-128k", "qwen3.8:27b", "qwen2.5:3b")
bad = []
for job in jobs:
    text = json.dumps(job, sort_keys=True)
    if any(model in text for model in obsolete):
        bad.append(f"{job.get('id')}: obsolete model reference")
    for key in ("model", "model_snapshot"):
        value = job.get(key)
        if value and ("qwen" in value or value.startswith("nomic-")) and value != primary:
            bad.append(f"{job.get('id')}: {key}={value}")
if bad:
    print("; ".join(bad))
    raise SystemExit(1)
PY
then
  pass "scheduled Hermes jobs use the canonical model policy"
else
  fail "scheduled Hermes jobs violate the canonical model policy"
fi

for warmup in \
  "$REPO_ROOT/scripts/hermes-preload-models.sh" \
  "$HOME/ollma-warmup.sh" \
  "$HOME/humanvalueexchange/hermes/scripts/hermes-preload-models.sh"; do
  if [[ ! -f "$warmup" ]]; then
    warn "warmup script not found: $warmup"
  elif grep -q 'qwen3.8-hermes:27b-128k' "$warmup" && \
       grep -q 'qwen3.8-distill-2b:q4_k_m' "$warmup"; then
    pass "warmup script uses canonical model policy: $warmup"
  else
    fail "warmup script violates canonical model policy: $warmup"
  fi
done

compare_file() {
  local source="$1"
  local destination="$2"
  if [[ ! -f "$destination" ]]; then
    fail "managed file is missing: $destination"
  elif cmp -s "$source" "$destination"; then
    pass "$(basename "$destination") matches repository source"
  else
    fail "$(basename "$destination") differs from repository source"
  fi
}

compare_file "$REPO_ROOT/dotfiles/SOUL.md" "$PROFILE/SOUL.md"
compare_file "$REPO_ROOT/dotfiles/inject-market-data.sh" "$HOME/.hermes/agent-hooks/inject-market-data.sh"

declare -a managed_units=(
  hermes-mcp.service
  hermes-model-preload.service
  hve-intake.service
  hve-intake.path
)
for unit in "${managed_units[@]}"; do
  compare_file "$REPO_ROOT/dotfiles/$unit" "$UNIT_DIR/$unit"
done

if systemctl --user daemon-reload >/dev/null 2>&1; then
  for unit in hermes-mcp.service hermes-model-preload.service hve-intake.path; do
    systemctl --user is-enabled "$unit" >/dev/null 2>&1 \
      && pass "$unit is enabled" \
      || warn "$unit is not enabled"
  done
  systemctl --user is-active hermes-mcp.service >/dev/null 2>&1 \
    && pass "hermes-mcp.service is active" \
    || fail "hermes-mcp.service is not active"
else
  fail "user systemd is unavailable"
fi

if command -v ollama >/dev/null 2>&1; then
  models="$(ollama list 2>/dev/null | awk 'NR > 1 {print $1}')"
  resident_models="$(python3 - "$REPO_ROOT/config/llm-stack.yaml" <<'PY'
import sys
from pathlib import Path
import yaml

manifest = yaml.safe_load(Path(sys.argv[1]).read_text())
for entry in manifest["resident"].values():
    print(entry["model"])
PY
)"
  while read -r model; do
    [[ -z "$model" ]] && continue
    if grep -Fxq "$model" <<<"$models" || grep -Fq "${model}:" <<<"$models"; then
      pass "Ollama model available: $model"
    else
      fail "Ollama model missing: $model"
    fi
  done <<<"$resident_models"
  loaded_models="$(ollama ps 2>/dev/null | awk 'NR > 1 {print $1}')"
  while read -r model; do
    [[ -z "$model" ]] && continue
    if grep -Fxq "$model" <<<"$loaded_models" || grep -Fq "${model}:" <<<"$loaded_models"; then
      pass "Ollama resident model loaded: $model"
    else
      fail "Ollama resident model is not loaded: $model"
    fi
  done <<<"$resident_models"
else
  fail "ollama command is unavailable"
fi

if (( errors > 0 )); then
  printf 'DRIFT CHECK FAILED errors=%d\n' "$errors"
  exit 1
fi
printf 'DRIFT CHECK PASSED\n'
