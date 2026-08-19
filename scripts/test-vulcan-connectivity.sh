#!/usr/bin/env bash
# test-vulcan-connectivity.sh — Validate Vulcan (WSL) can reach all Hermes services on DGX Spark
# Run this from Vulcan's WSL terminal before starting any dev loop work.
# Usage: bash test-vulcan-connectivity.sh [DGX_IP]
# Default DGX_IP: [DGX_LAN_IP]

set -euo pipefail

DGX="${1:-[DGX_TAILSCALE_IP]}"  # DGX Spark Tailscale IP (LAN fallback: [DGX_LAN_IP])
PASS=0
FAIL=0

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS${NC}  $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}❌ FAIL${NC}  $1"; FAIL=$((FAIL+1)); }
info() { echo -e "${BLUE}→${NC} $1"; }

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Vulcan → Hermes Connectivity Check                         ║"
echo "║   Target DGX Spark: $DGX                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Test 1: Network reachability ─────────────────────────────────
info "Pinging DGX Spark..."
if ping -c 2 -W 3 "$DGX" > /dev/null 2>&1; then
  pass "DGX Spark reachable at $DGX"
else
  fail "DGX Spark unreachable at $DGX — check LAN/VPN"
  echo "Cannot continue without network. Exiting."
  exit 1
fi

# ── Test 2: Ollama API ───────────────────────────────────────────
info "Testing Ollama API (port 11434)..."
OLLAMA_RESP=$(curl -s --max-time 5 "http://$DGX:11434/api/version" 2>/dev/null || echo "")
if echo "$OLLAMA_RESP" | grep -q '"version"'; then
  OLLAMA_VER=$(echo "$OLLAMA_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])" 2>/dev/null || echo "unknown")
  pass "Ollama API responding — v$OLLAMA_VER"
else
  fail "Ollama API not responding on $DGX:11434 — is ollama.service running?"
fi

# ── Test 3: Ollama models loaded ─────────────────────────────────
info "Checking current local Hermes model stack is loaded..."
MODELS_RESP=$(curl -s --max-time 5 "http://$DGX:11434/api/ps" 2>/dev/null || echo "{}")
for model in "qwen3.5:27b-128k" "gpt-oss:20b" "qwen2.5:3b" "nomic-embed-text"; do
  if echo "$MODELS_RESP" | grep -q "$model"; then
    pass "Model loaded: $model"
  else
    fail "Model NOT loaded: $model — run: ssh hans@$DGX 'ollama run $model &'"
  fi
done

# ── Test 4: MCP server ───────────────────────────────────────────
info "Testing MCP server (port 8765)..."
if nc -zw3 "$DGX" 8765 2>/dev/null; then
  pass "MCP server port 8765 open"
else
  fail "MCP server not reachable on $DGX:8765 — check: ssh hans@$DGX 'ps aux | grep hermes_mcp'"
fi

# ── Test 5: SSH access ───────────────────────────────────────────
info "Testing SSH access (port 22)..."
if nc -zw3 "$DGX" 22 2>/dev/null; then
  pass "SSH port 22 open"
else
  fail "SSH not reachable on $DGX:22"
fi

info "Testing SSH login + hermes version..."
SSH_RESULT=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "hans@$DGX" "~/.local/bin/hermes --version 2>/dev/null || hermes --version 2>/dev/null || echo HERMES_NOT_FOUND" 2>/dev/null || echo "SSH_FAILED")
if echo "$SSH_RESULT" | grep -qi "hermes"; then
  pass "SSH login OK — $SSH_RESULT"
elif [ "$SSH_RESULT" = "SSH_FAILED" ]; then
  fail "SSH login failed — add Vulcan's public key to hans@$DGX:~/.ssh/authorized_keys"
else
  fail "SSH OK but hermes not found: $SSH_RESULT"
fi

# ── Test 6: Hermes-cfo repo present ─────────────────────────────
info "Checking hermes-cfo repo on DGX Spark..."
REPO_CHECK=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "hans@$DGX" "test -f ~/hermes-cfo/scripts/test-tool-enforcement.sh && echo FOUND || echo MISSING" 2>/dev/null || echo "SSH_FAILED")
if [ "$REPO_CHECK" = "FOUND" ]; then
  pass "hermes-cfo repo present at ~/hermes-cfo"
else
  fail "hermes-cfo repo missing — run: ssh hans@$DGX 'git clone https://github.com/humanvalueexchange/hermes-cfo.git ~/hermes-cfo'"
fi

# ── Summary ──────────────────────────────────────────────────────
TOTAL=$((PASS+FAIL))
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
printf "║  Results: %-3s passed  %-3s failed  (%-2s total)                  ║\n" $PASS $FAIL $TOTAL
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ $FAIL -gt 0 ]; then
  echo -e "${RED}❌ $FAIL check(s) failed. Fix the issues above before starting the dev loop.${NC}"
  exit 1
else
  echo -e "${GREEN}✅ All checks passed. Vulcan is ready to run the dev loop.${NC}"
  echo "   Next: bash ~/hermes-cfo/scripts/test-tool-enforcement.sh (run via SSH)"
  exit 0
fi
