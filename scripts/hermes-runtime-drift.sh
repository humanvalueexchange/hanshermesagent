#!/usr/bin/env bash
# Verify that the live Hermes runtime matches the hermes-cfo repository contract.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVE_PROFILE="$(cat "$HOME/.hermes/active_profile" 2>/dev/null || printf 'main')"
PROFILE="${HERMES_PROFILE:-$HOME/.hermes/profiles/$ACTIVE_PROFILE}"
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
  sed "s/\${HVE_MCP_API_KEY}/${HVE_MCP_API_KEY:-}/g" \
    "$REPO_ROOT/config/hermes-config.template.yaml" > "$rendered_config"
  if [[ ! -f "$PROFILE/config.yaml" ]]; then
    fail "live Hermes config is missing: $PROFILE/config.yaml"
  elif python3 - "$rendered_config" "$PROFILE/config.yaml" <<'PY'
import sys
from pathlib import Path

import yaml

template = yaml.safe_load(Path(sys.argv[1]).read_text())
live = yaml.safe_load(Path(sys.argv[2]).read_text())

def provider_config(document):
    providers = document.get("providers") or {}
    return next(iter(providers.values()), {})

expected_models = {"qwen3.5:27b-128k", "gpt-oss:20b", "qwen2.5:3b", "nomic-embed-text"}
live_provider = provider_config(live)
checks = [
    (live.get("model", {}).get("default") == template.get("model", {}).get("default"), "primary model"),
    (live_provider.get("default_model") == template.get("model", {}).get("default"), "provider default model"),
    (set(live_provider.get("models") or []) == expected_models, "approved Ollama model catalog"),
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
else
  fail "cannot render live Hermes config without the environment file"
fi

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
  while read -r model; do
    [[ -z "$model" ]] && continue
    if grep -Fxq "$model" <<<"$models" || grep -Fq "${model}:" <<<"$models"; then
      pass "Ollama model available: $model"
    else
      fail "Ollama model missing: $model"
    fi
  done < <(grep -oE 'ollama (run|pull) [^[:space:]]+' "$REPO_ROOT/scripts/hermes-preload-models.sh" | awk '{print $2}' | sort -u)
else
  fail "ollama command is unavailable"
fi

if (( errors > 0 )); then
  printf 'DRIFT CHECK FAILED errors=%d\n' "$errors"
  exit 1
fi
printf 'DRIFT CHECK PASSED\n'
