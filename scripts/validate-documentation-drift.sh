#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

paths=(
  "$REPO_ROOT/README.md"
  "$REPO_ROOT/SECURITY.md"
  "$REPO_ROOT/config"
  "$REPO_ROOT/cron"
  "$REPO_ROOT/dotfiles"
  "$REPO_ROOT/prompts"
  "$REPO_ROOT/scripts"
  "$REPO_ROOT/skills"
)

if rg -n -i \
  --glob '!validate-kraken-market-data.sh' \
  --glob '!validate-documentation-drift.sh' \
  'hermes-v2|/home/hans/hermes-v2|profiles/main|BTC/USDT|BTC_USDT|Mattermost|Hugging Face|Transformers' \
  "${paths[@]}" >"$TMP_FILE"; then
    echo "FAIL documentation drift detected:"
    cat "$TMP_FILE"
    exit 1
fi

grep -Fq '**Status:** Historical reference' \
  "$REPO_ROOT/docs/architecture/HVE-Knowledge-Architecture-v1.1.md" ||
  { echo "FAIL architecture document is not marked historical"; exit 1; }
grep -Fq '**Status:** Historical —' \
  "$REPO_ROOT/docs/test-plans/automated-intake-phase1-test-plan.md" ||
  { echo "FAIL intake test plan is not marked historical"; exit 1; }

echo "PASS documentation drift scan"
