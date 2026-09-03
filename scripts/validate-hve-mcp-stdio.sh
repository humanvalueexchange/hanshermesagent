#!/usr/bin/env bash
# validate-hve-mcp-stdio.sh
# Validates the dedicated HVE MCP 2 stdio runtime without mutating production data.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="${REPO_DIR}/mcp"
VENV_DIR="${HOME}/.hermes-mcp-venv"
PYTHON="${VENV_DIR}/bin/python"
HANS_CONFIG="${HOME}/.hermes/profiles/hanshermesagent/config.yaml"
LIBRARIAN_CONFIG="${HOME}/.hermes/profiles/hve-librarian/config.yaml"

check_file() {
    local label="$1"
    local path="$2"
    if [ -f "${path}" ]; then
        echo "PASS ${label}"
    else
        echo "FAIL ${label} — missing ${path}"
        exit 1
    fi
}

check_file "dedicated Python" "${PYTHON}"
check_file "MCP project manifest" "${MCP_DIR}/pyproject.toml"
check_file "MCP lockfile" "${MCP_DIR}/uv.lock"
check_file "Hans profile config" "${HANS_CONFIG}"
check_file "Librarian profile config" "${LIBRARIAN_CONFIG}"

(cd "${MCP_DIR}" && uv lock --check)

"${PYTHON}" - <<'PY'
from importlib.metadata import version

expected = {"fastmcp": "4.0.2", "mcp": "2.0.0"}
for package, wanted in expected.items():
    actual = version(package)
    if actual != wanted:
        raise SystemExit(f"{package} is {actual}, expected {wanted}")
    print(f"PASS {package}=={actual}")
PY

grep -Fq 'mcp[cli]==2.0.0' "${MCP_DIR}/pyproject.toml"
grep -Fq 'fastmcp==4.0.2' "${MCP_DIR}/pyproject.toml"
echo "PASS exact MCP 2 dependency pins"

"${PYTHON}" - "${HANS_CONFIG}" "${LIBRARIAN_CONFIG}" "${PYTHON}" <<'PY'
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

hans_config, librarian_config, python = map(Path, sys.argv[1:4])
expected_config = {
    hans_config: (
        "hermes-coder-dispatch",
        "hve-link-collector",
        "hve-link-library",
        "hve-decision-ledger",
    ),
    librarian_config: ("hve-link-collector", "hve-librarian-communications"),
}
for config, names in expected_config.items():
    text = config.read_text()
    for name in names:
        marker = f"  {name}:\n    command: {python}\n"
        if marker not in text:
            raise SystemExit(f"{config}: {name} is not configured for the dedicated runtime")
print("PASS profile launch commands")

servers = [
    ("link-collector", Path("/home/hans/hanshermesagent/mcp/link_collector_server.py"),
     {"archive_link", "archive_youtube", "archive_pdf", "archive_proton_file"}),
    ("link-library", Path("/home/hans/hanshermesagent/mcp/link_library_server.py"),
     {"search_link_library", "read_link_document", "read_link_document_chunks",
      "annotate_record", "list_record_annotations", "list_recent_links"}),
    ("decision-ledger", Path("/home/hans/hanshermesagent/mcp/decision_log_server.py"),
     {"append_decision_events", "list_decision_events", "list_ledger_handoff_candidates"}),
    ("coder-dispatch", Path("/home/hans/.hermes/profiles/hermes-coder/dispatch_mcp.py"),
     {"coder_enqueue", "coder_status"}),
    ("librarian-comms", Path("/home/hans/hanshermesagent/mcp/librarian_comms_server.py"),
     {"write_agent_communication", "publish_agent_communication",
      "create_enhancement_backlog_issue", "comment_on_github_issue",
      "close_github_issue", "update_github_issue"}),
]

async def check_server(name, script, expected):
    params = StdioServerParameters(command=str(python), args=[str(script)], cwd=Path.home())
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=20)
                result = await asyncio.wait_for(session.list_tools(), timeout=20)
                actual = {tool.name for tool in result.tools}
                if actual != expected:
                    raise SystemExit(
                        f"{name}: tool mismatch; expected {sorted(expected)}, got {sorted(actual)}"
                    )
                print(f"PASS {name} initialize/tools-list ({len(actual)} tools)")

async def main():
    for name, script, expected in servers:
        await check_server(name, script, expected)

asyncio.run(main())
PY

echo "PASS all dedicated HVE MCP stdio checks"
