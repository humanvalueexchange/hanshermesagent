#!/usr/bin/env bash
# validate-hermes-mcp.sh
# Validates the HVE Hermes MCP Server is correctly installed and responding.

set -euo pipefail

PORT="${HVE_MCP_PORT:-8765}"
ENV_FILE="${HOME}/.hermes-mcp.env"
ACTIVE_PROFILE="$(cat "${HOME}/.hermes/active_profile" 2>/dev/null || echo default)"
CONFIG_FILE="${HOME}/.hermes/profiles/${ACTIVE_PROFILE}/config.yaml"
SKILLS_DIR="${HOME}/hermes-cfo/skills/hve"
KNOWLEDGE_PYTHON="${HOME}/.hve-knowledge/venv/bin/python3"
KNOWLEDGE_SEARCH_SCRIPT="${HOME}/hermes-cfo/mcp/tools/knowledge/search.py"
PASS=0
FAIL=0

check() {
    local label="$1"
    local result="$2"
    if [ "${result}" = "ok" ]; then
        echo "PASS ${label}"
        ((PASS++)) || true
    else
        echo "FAIL ${label} — ${result}"
        ((FAIL++)) || true
    fi
}

# systemd service
state=$(systemctl --user is-active hermes-mcp 2>/dev/null || echo "inactive")
check "hermes-mcp service active" "$([ "$state" = "active" ] && echo ok || echo "$state")"

# env file + API key
check "env file exists" "$([ -f "${ENV_FILE}" ] && echo ok || echo "missing ${ENV_FILE}")"
check "API key set" "$(grep -q 'HVE_MCP_API_KEY=.' "${ENV_FILE}" 2>/dev/null && echo ok || echo "HVE_MCP_API_KEY empty or missing")"

# agent card
card=$(curl -sf "http://127.0.0.1:${PORT}/.well-known/agent.json" 2>/dev/null || echo "")
check "agent card reachable" "$([ -n "${card}" ] && echo ok || echo "http://127.0.0.1:${PORT}/.well-known/agent.json unreachable")"
check "agent card has name" "$(echo "${card}" | grep -q 'HVE Hermes' && echo ok || echo "name field missing")"
agent_card_tool_count=$(CARD="${card}" python3 - <<'PY'
import json
import os
text = os.environ.get("CARD", "")
try:
    data = json.loads(text)
    print(len(data.get("capabilities", {}).get("tools", [])))
except Exception:
    print("parse_error")
PY
)
check "agent card tool count" "$([ "${agent_card_tool_count}" = "17" ] && echo ok || echo "expected 17, got ${agent_card_tool_count}")"

# MCP endpoint — streamable-http requires session init before tools/list
API_KEY=$(grep HVE_MCP_API_KEY "${ENV_FILE}" 2>/dev/null | cut -d= -f2- || echo "")

# Step 1: initialize — get session ID from response header
init_headers=$(curl -si -X POST "http://127.0.0.1:${PORT}/mcp" \
    -H "Content-Type: application/json" \
    -H "X-HVE-API-Key: ${API_KEY}" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"validate","version":"1.0"}}}' \
    2>/dev/null || echo "")
SESSION_ID=$(echo "${init_headers}" | grep -i "mcp-session-id:" | head -1 | awk '{print $2}' | tr -d '\r')
check "MCP endpoint responding" "$([ -n "${SESSION_ID}" ] && echo ok || echo "POST /mcp returned nothing")"

# Step 2: tools/list with session ID
mcp_resp=$(curl -sf -X POST "http://127.0.0.1:${PORT}/mcp" \
    -H "Content-Type: application/json" \
    -H "X-HVE-API-Key: ${API_KEY}" \
    -H "Accept: application/json, text/event-stream" \
    -H "mcp-session-id: ${SESSION_ID}" \
    -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' 2>/dev/null || echo "")
check "MCP tools list returned" "$(echo "${mcp_resp}" | grep -q 'get_btc_forecast' && echo ok || echo "tools not found in response")"
mcp_tool_count=$(MCP_RESP="${mcp_resp}" python3 - <<'PY'
import json
import os

text = os.environ.get("MCP_RESP", "")
for line in text.splitlines():
    if line.startswith("data: "):
        text = line[6:]
try:
    data = json.loads(text)
    print(len(data.get("result", {}).get("tools", [])))
except Exception:
    print("parse_error")
PY
)
check "MCP tools count" "$([ "${mcp_tool_count}" = "17" ] && echo ok || echo "expected 17, got ${mcp_tool_count}")"

missing_tools=()
for tool in get_mempool_fees get_mempool_depth get_block_status get_lightning_network_stats; do
    if ! echo "${mcp_resp}" | grep -q "${tool}"; then
        missing_tools+=("${tool}")
    fi
done
if [ "${#missing_tools[@]}" -eq 0 ]; then
    check "Mempool tools registered" "ok"
else
    check "Mempool tools registered" "missing ${missing_tools[*]}"
fi

check "skills external_dirs configured" "$(grep -q '/home/hans/hermes-cfo/skills/hve' "${CONFIG_FILE}" 2>/dev/null && echo ok || echo "skills/hve not configured in ${CONFIG_FILE}")"
check "native skills directory exists" "$([ -d "${SKILLS_DIR}" ] && echo ok || echo "missing ${SKILLS_DIR}")"
skill_count=$(find "${SKILLS_DIR}" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
check "native HVE skill files present" "$([ "${skill_count}" = "5" ] && echo ok || echo "expected 5, got ${skill_count}")"
check "knowledge venv python exists" "$([ -x "${KNOWLEDGE_PYTHON}" ] && echo ok || echo "missing ${KNOWLEDGE_PYTHON}")"
check "knowledge search script exists" "$([ -f "${KNOWLEDGE_SEARCH_SCRIPT}" ] && echo ok || echo "missing ${KNOWLEDGE_SEARCH_SCRIPT}")"

# mempool tools presence
check "mempool tool: get_mempool_fees" "$(echo "${mcp_resp}" | grep -q 'get_mempool_fees' && echo ok || echo "tool not registered")"
check "mempool tool: get_mempool_depth" "$(echo "${mcp_resp}" | grep -q 'get_mempool_depth' && echo ok || echo "tool not registered")"
check "mempool tool: get_block_status" "$(echo "${mcp_resp}" | grep -q 'get_block_status' && echo ok || echo "tool not registered")"
check "mempool tool: get_lightning_network_stats" "$(echo "${mcp_resp}" | grep -q 'get_lightning_network_stats' && echo ok || echo "tool not registered")"
check "GitHub tool: read_github_issue" "$(echo "${mcp_resp}" | grep -q 'read_github_issue' && echo ok || echo "tool not registered")"
check "GitHub tool: comment_github_issue" "$(echo "${mcp_resp}" | grep -q 'comment_github_issue' && echo ok || echo "tool not registered")"
check "GitHub tool: list_github_issues" "$(echo "${mcp_resp}" | grep -q 'list_github_issues' && echo ok || echo "tool not registered")"

# tasks file
TASKS_FILE="${HOME}/hermes-cfo/logs/tasks/tasks.json"
check "tasks file exists" "$([ -f "${TASKS_FILE}" ] && echo ok || echo "missing ${TASKS_FILE}")"

echo ""
if [ "${FAIL}" -eq 0 ]; then
    echo "PASS all ${PASS} checks passed — Hermes MCP Server is healthy."
else
    echo "RESULT ${PASS} passed, ${FAIL} failed."
    exit 1
fi
