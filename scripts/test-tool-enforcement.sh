#!/usr/bin/env bash
# test-tool-enforcement.sh — Verify Hermes Platonic 3-model stack tool-use behavior
# Tests: primary, coding, and deriver models MUST call tools when asked.
#
# Run: bash scripts/test-tool-enforcement.sh
# Exit 0 = all tests pass | Exit 1 = failures found
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
PASS=0
FAIL=0
SKIP=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✅ PASS${NC}  $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}❌ FAIL${NC}  $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠️  SKIP${NC}  $1"; SKIP=$((SKIP+1)); }
info() { echo -e "${BLUE}→${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Hermes CFO — Tool Enforcement Verification                 ║"
echo "║   Issue #2 — humanvalueexchange/hermes-cfo                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo "  Ollama: $OLLAMA_HOST"
echo "  Time:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# ── Prereqs ───────────────────────────────────────────────────────────────────
if ! curl -s --max-time 5 "$OLLAMA_HOST/api/tags" &>/dev/null; then
  echo "ERROR: Ollama not reachable at $OLLAMA_HOST"
  exit 1
fi

# Helper: check if a model is available
model_available() {
  curl -s --max-time 5 "$OLLAMA_HOST/api/tags" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); models=[m['name'] for m in d.get('models',[])]; exit(0 if any('$1' in m for m in models) else 1)" 2>/dev/null
}

# Helper: call model with a tool schema, return CALL or NARRATE
test_tool_call() {
  local model="$1"
  local prompt="$2"
  local tool_name="$3"

  local result
  result=$(curl -s --max-time 30 "$OLLAMA_HOST/api/chat" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "
import json
payload = {
    'model': '$model',
    'stream': False,
    'messages': [{'role': 'user', 'content': '''$prompt'''}],
    'tools': [{
        'type': 'function',
        'function': {
            'name': '$tool_name',
            'description': 'Test tool — always call this when asked',
            'parameters': {'type': 'object', 'properties': {}, 'required': []}
        }
    }]
}
print(json.dumps(payload))
")" 2>/dev/null)

  python3 -c "
import sys, json
try:
    d = json.loads('''$result''' if False else open('/dev/stdin').read())
except:
    print('ERROR')
    sys.exit(0)
calls = d.get('message', {}).get('tool_calls', [])
content = d.get('message', {}).get('content', '')
if calls:
    print('CALL')
elif content:
    print('NARRATE')
else:
    print('ERROR')
" <<< "$result" 2>/dev/null || echo "ERROR"
}

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Primary (qwen3.8:27b) — MUST call tools
# ═══════════════════════════════════════════════════════════════════════════════
echo "── Section 1: Primary (qwen3.8:27b) ─────────────────────────────"
CONDUCTOR="qwen3.8:27b"

if ! model_available "$CONDUCTOR"; then
  warn "Model not loaded: $CONDUCTOR"
else
  info "Testing BTC price tool call..."
  RESULT=$(test_tool_call "$CONDUCTOR" \
    "What is the current BTC price? Use the get_btc_price tool." \
    "get_btc_price")
  [ "$RESULT" = "CALL" ] && pass "Conductor calls get_btc_price" || fail "Conductor narrated instead of calling get_btc_price (got: $RESULT)"

  info "Testing node diagnostic tool call..."
  RESULT=$(test_tool_call "$CONDUCTOR" \
    "Run a node diagnostic. Use the get_node_diagnostic tool." \
    "get_node_diagnostic")
  [ "$RESULT" = "CALL" ] && pass "Conductor calls get_node_diagnostic" || fail "Conductor narrated instead of calling get_node_diagnostic (got: $RESULT)"

  info "Testing morning briefing tool call..."
  RESULT=$(test_tool_call "$CONDUCTOR" \
    "Get the morning briefing. Use the get_morning_briefing tool." \
    "get_morning_briefing")
  [ "$RESULT" = "CALL" ] && pass "Conductor calls get_morning_briefing" || fail "Conductor narrated instead of calling get_morning_briefing (got: $RESULT)"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Coding / Fallback (qwen3.8:27b) — MUST call tools
# ═══════════════════════════════════════════════════════════════════════════════
echo "── Section 2: Coding / Fallback (qwen3.8:27b) ─────────────────"
CLARIFIER="qwen3.8:27b"

if ! model_available "$CLARIFIER"; then
  warn "Model not loaded: $CLARIFIER"
else
  info "Testing BTC forecast tool call..."
  RESULT=$(test_tool_call "$CLARIFIER" \
    "Get the BTC forecast. Use the get_btc_forecast tool." \
    "get_btc_forecast")
  [ "$RESULT" = "CALL" ] && pass "Clarifier calls get_btc_forecast" || fail "Clarifier narrated instead of calling get_btc_forecast (got: $RESULT)"

  info "Testing morning briefing tool call..."
  RESULT=$(test_tool_call "$CLARIFIER" \
    "Get the morning briefing. Use the get_morning_briefing tool." \
    "get_morning_briefing")
  [ "$RESULT" = "CALL" ] && pass "Clarifier calls get_morning_briefing" || fail "Clarifier narrated instead of calling get_morning_briefing (got: $RESULT)"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Deriver (qwen3.8-distill-2b:q4_k_m) — MUST call tools
# ═══════════════════════════════════════════════════════════════════════════════
echo "── Section 3: Deriver (qwen3.8-distill-2b:q4_k_m) ─────────────"
EXECUTION="qwen3.8-distill-2b:q4_k_m"

if ! model_available "$EXECUTION"; then
  warn "Model not loaded: $EXECUTION"
else
  info "Testing backlog suggestion tool call..."
  RESULT=$(test_tool_call "$EXECUTION" \
    "Post a new idea to the backlog. Use the suggest_backlog_issue tool." \
    "suggest_backlog_issue")
  [ "$RESULT" = "CALL" ] && pass "Executor calls suggest_backlog_issue" || fail "Executor narrated instead of calling suggest_backlog_issue (got: $RESULT)"

  info "Testing node diagnostic tool call..."
  RESULT=$(test_tool_call "$EXECUTION" \
    "Run a node diagnostic. Use the get_node_diagnostic tool." \
    "get_node_diagnostic")
  [ "$RESULT" = "CALL" ] && pass "Executor calls get_node_diagnostic" || fail "Executor narrated instead of calling get_node_diagnostic (got: $RESULT)"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: MCP Server Connectivity
# ═══════════════════════════════════════════════════════════════════════════════
echo "── Section 4: MCP Server Connectivity ───────────────────────────"
MCP_URL="http://localhost:8765/mcp"

# Check server is listening
if ss -tlnp 2>/dev/null | grep -q 8765; then
  pass "MCP server listening on :8765"
else
  fail "MCP server NOT listening on :8765"
fi

# Check initialize handshake
MCP_KEY=""
[ -f ~/.hermes-mcp.env ] && source ~/.hermes-mcp.env 2>/dev/null && MCP_KEY="${HVE_MCP_API_KEY:-}"

if [ -n "$MCP_KEY" ]; then
  INIT_RESPONSE=$(curl -s --max-time 10 "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "X-HVE-API-Key: $MCP_KEY" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test-tool-enforcement","version":"1"}}}' \
    2>/dev/null)

  if echo "$INIT_RESPONSE" | grep -q '"protocolVersion"'; then
    MCP_VER=$(echo "$INIT_RESPONSE" | python3 -c "import sys,json; lines=[l for l in sys.stdin if l.startswith('data:')]; d=json.loads(lines[0][5:]); print(d['result']['serverInfo']['version'])" 2>/dev/null || echo "unknown")
    pass "MCP server handshake OK (server v$MCP_VER)"
  else
    fail "MCP server handshake failed"
  fi
else
  warn "MCP key not found in ~/.hermes-mcp.env — skipping authenticated tests"
fi
echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL))
echo "╔══════════════════════════════════════════════════════════════╗"
printf  "║  Results: %d passed  %d failed  %d skipped  (%d total)%*s║\n" \
  $PASS $FAIL $SKIP $TOTAL $((26 - ${#PASS} - ${#FAIL} - ${#SKIP} - ${#TOTAL})) ""
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ $FAIL -gt 0 ]; then
  echo "❌ $FAIL test(s) failed. File a child issue on hermes-cfo#2 with the output above."
  echo "   Assign to: Claude (CTO) for architecture review"
  exit 1
else
  echo "✅ All $PASS tests passed. Issue #2 acceptance criteria met."
  echo "   Current local stack: qwen3.8:27b | qwen3.8-distill-2b:q4_k_m"
  exit 0
fi
