#!/usr/bin/env python3
"""
HVE Hermes MCP Server

Exposes Hermes CFO capabilities as MCP tools for Copilot Studio
and any other MCP-compatible agent client.

Transport: Streamable HTTP on port 8765
Auth:      X-HVE-API-Key header (HVE_MCP_API_KEY is required for protected paths)
Tunnel:    Tailscale Funnel → public HTTPS endpoint for Copilot Studio
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from market_intelligence import get_market_intelligence_data
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.github_issues import (  # noqa: E402
    comment_github_issue as github_comment_issue,
    list_github_issues as github_list_issues,
    read_github_issue as github_read_issue,
)
from tools.knowledge import search_knowledge_vault as knowledge_search  # noqa: E402
from tools.link_collector import archive_link as collect_link  # noqa: E402
from tools.pdf_collector import archive_pdf as collect_pdf  # noqa: E402
from tools.mempool.tools import (  # noqa: E402
    get_block_status,
    get_block_status as _mempool_get_block_status,
    get_lightning_network_stats,
    get_lightning_network_stats as _mempool_get_lightning_stats,
    get_mempool_depth,
    get_mempool_depth as _mempool_get_mempool_depth,
    get_mempool_fees,
    get_mempool_fees as _mempool_get_mempool_fees,
)

# ── paths ────────────────────────────────────────────────────────────────────
REPO_DIR = Path.home() / "hanshermesagent"
BRIEFINGS_DIR = REPO_DIR / "logs" / "briefings"
TASKS_FILE = REPO_DIR / "logs" / "tasks" / "tasks.json"
OLLAMA_API = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
TOOL_NAMES = [
    "get_btc_forecast",
    "get_market_intelligence",
    "get_mempool_fees",
    "get_mempool_depth",
    "get_block_status",
    "get_lightning_network_stats",
    "get_morning_briefing",
    "get_capability_assessment",
    "search_knowledge_vault",
    "archive_link",
    "archive_pdf",
    "create_task",
    "get_client_context",
    "get_node_diagnostic",
    "suggest_backlog_issue",
    "vote_backlog_issue",
    "read_github_issue",
    "comment_github_issue",
    "list_github_issues",
]

# ── server ───────────────────────────────────────────────────────────────────
# DNS rebinding protection disabled — we enforce auth via X-HVE-API-Key instead.
# This allows the server to accept requests from any host (Tailscale Funnel, etc.)
mcp = FastMCP(
    name="HVE Hermes",
    instructions=(
        "You are connected to the Hermes CFO intelligence system running on the "
        "Human Value Exchange DGX Spark. Use these tools to retrieve financial "
        "forecasts, live mempool and Lightning intelligence, morning briefings, "
        "vault knowledge, GitHub issue context, and client context on behalf of "
        "HVE clients and the executive team. Link and PDF collection tools are "
        "restricted to the local HVE knowledge library."
    ),
)

for tool in (
    get_mempool_fees,
    get_mempool_depth,
    get_block_status,
    get_lightning_network_stats,
):
    mcp.tool()(tool)


# ── auth middleware ──────────────────────────────────────────────────────────
class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce X-HVE-API-Key header when HVE_MCP_API_KEY env var is set."""

    # Paths that are always public (no auth required)
    PUBLIC_PATHS = {"/.well-known/agent.json", "/health"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.PUBLIC_PATHS:
            return await call_next(request)
        expected = os.environ.get("HVE_MCP_API_KEY", "")
        if not expected:
            return JSONResponse({"error": "MCP authentication is not configured"}, status_code=503)
        provided = request.headers.get("X-HVE-API-Key", "")
        if provided != expected:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


# ── helpers ──────────────────────────────────────────────────────────────────
def _fetch_json(url: str, timeout: int = 10) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "HermesMCP/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def _latest_briefing(prefix: str) -> Path | None:
    files = sorted(BRIEFINGS_DIR.glob(f"{prefix}-*.md"), reverse=True)
    return files[0] if files else None


def _load_tasks() -> list[dict]:
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_tasks(tasks: list[dict]) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2))


# ── tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_btc_forecast() -> str:
    """
    Get a live BTC/USD short-term directional forecast from Kraken.

    Returns current price, predicted price, direction (up/down/flat),
    confidence level, rationale, and invalidation condition.
    Uses Kraken public API data — no API key required.
    """
    try:
        klines = _fetch_json(
            "https://api.kraken.com/0/public/OHLC?pair=XXBTZUSD&interval=1"
        )
        ticker = _fetch_json("https://api.kraken.com/0/public/Ticker?pair=XXBTZUSD")
    except (KeyError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return f"ERROR: market data unavailable — {exc}"

    closes = [float(row[4]) for row in klines["result"]["XXBTZUSD"][:-1]]
    if len(closes) < 31:
        return "ERROR: insufficient market history"

    current = float(ticker["result"]["XXBTZUSD"]["c"][0])
    r5 = (closes[-1] - closes[-6]) / closes[-6]
    r15 = (closes[-1] - closes[-16]) / closes[-16]
    r30 = (closes[-1] - closes[-31]) / closes[-31]
    momentum = (0.5 * r5) + (0.3 * r15) + (0.2 * r30)
    move = max(min(momentum * 0.6, 0.004), -0.004)
    predicted = current * (1 + move)

    direction = "up" if move > 0.0005 else ("down" if move < -0.0005 else "flat")
    agreement = sum(
        1 for v in (r5, r15, r30)
        if (v > 0 and move > 0) or (v < 0 and move < 0) or (abs(v) < 0.0005 and direction == "flat")
    )
    confidence = "high" if agreement == 3 and abs(move) > 0.001 else "medium" if agreement >= 2 else "low"

    return (
        f"BTC Forecast — {datetime.now().strftime('%Y-%m-%d %H:%M ET')}\n"
        f"Current price:   ${current:,.2f}\n"
        f"Predicted price: ${predicted:,.2f}\n"
        f"Direction:       {direction.upper()}\n"
        f"Confidence:      {confidence}\n"
        f"Rationale:       5m {r5:+.2%} | 15m {r15:+.2%} | 30m {r30:+.2%} momentum\n"
        f"Invalidation:    if next 5m candle breaks current 15m direction\n"
        f"Source:          Kraken public API (live)"
    )


@mcp.tool()
def get_market_intelligence(topics: list[str] | None = None, limit: int = 5) -> dict:
    """
    Fetch live prediction market intelligence for BTC treasury decision support.

    Sources: Polymarket public feed (primary). Read-only. No auth. No positions.
    """
    return get_market_intelligence_data(topics=topics, limit=limit)


@mcp.tool()
def get_morning_briefing() -> str:
    """
    Retrieve the latest Hermes morning briefing.

    Returns the full text of today's (or most recent) morning briefing
    including system health, BTC outlook, and executive summary.
    """
    path = _latest_briefing("hermes-morning-briefing")
    if not path:
        return "No morning briefing found. The 06:30 cron job may not have run yet today."
    age_hours = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    content = path.read_text()
    return f"[Source: {path.name} — {age_hours:.1f}h ago]\n\n{content}"


@mcp.tool()
def get_capability_assessment() -> str:
    """
    Retrieve the latest Hermes capability assessment.

    Returns system health, service states, 4-agent model status,
    and the top capability gaps for the current trading day.
    """
    path = _latest_briefing("hermes-capability-assessment")
    if not path:
        return "No capability assessment found. The 02:00 nightly cron job may not have run yet."
    age_hours = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    content = path.read_text()
    return f"[Source: {path.name} — {age_hours:.1f}h ago]\n\n{content}"


@mcp.tool()
def search_knowledge_vault(query: str, max_results: int = 5) -> str:
    """
    Search the HVE knowledge vault for notes, documents, and sources.

    Performs a case-insensitive full-text search across all Markdown files
    in the canonical HVE knowledge vault at /hve-library/vault/hve-knowledge-vault.
    Returns matching excerpts with file paths as provenance citations.

    Args:
        query: Search terms (e.g. 'bitcoin risk management', 'trading psychology')
        max_results: Maximum number of matching files to return (default 5, max 20)
    """
    return knowledge_search(query, max_results, _run)


@mcp.tool()
def archive_link(url: str, capture_context: str | None = None) -> dict:
    """Archive one public HTTP(S) URL into the local HVE knowledge library."""
    return collect_link(url, capture_context)


@mcp.tool()
def archive_pdf(pdf_path: str, capture_context: str | None = None) -> dict:
    """Archive one approved Hans Hermes PDF attachment into the local HVE library."""
    return collect_pdf(pdf_path, capture_context)


@mcp.tool()
def create_task(
    title: str,
    description: str = "",
    priority: str = "normal",
    assigned_to: str = "Hans",
) -> str:
    """
    Create a follow-up task in the HVE task queue.

    Tasks are stored in hanshermesagent/logs/tasks/tasks.json and surfaced
    in the morning briefing and client context.

    Args:
        title: Short task title (required)
        description: Detailed description of what needs to be done
        priority: 'low', 'normal', or 'high'
        assigned_to: Who owns this task (default: Hans)
    """
    if not title.strip():
        return "ERROR: task title is required"

    tasks = _load_tasks()
    task = {
        "id": f"task-{int(datetime.now().timestamp())}",
        "title": title.strip(),
        "description": description.strip(),
        "priority": priority if priority in ("low", "normal", "high") else "normal",
        "assigned_to": assigned_to,
        "status": "open",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    tasks.append(task)
    _save_tasks(tasks)
    return f"Task created: [{task['id']}] {task['title']} (priority: {task['priority']}, assigned: {task['assigned_to']})"


@mcp.tool()
def get_client_context() -> str:
    """
    Get current HVE system context for personalized client responses.

    Returns:
    - System service health (Ollama, Open WebUI)
    - Currently loaded Ollama models
    - Open tasks from the HVE task queue
    - Latest briefing availability
    - Current BTC price (live)
    """
    lines = [f"HVE System Context — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    # service health
    services = {"ollama": "ollama", "open-webui": "open-webui"}
    lines.append("\n## Services")
    for label, name in services.items():
        _, state = _run(["systemctl", "is-active", name])
        lines.append(f"- {label}: {state or 'inactive'}")

    # loaded models
    lines.append("\n## Ollama models loaded")
    try:
        data = _fetch_json(f"{OLLAMA_API}/api/ps", timeout=5)
        models = data.get("models", [])
        if models:
            for m in models:
                size_gb = m.get("size", 0) / 1e9
                lines.append(f"- {m['name']} ({size_gb:.1f} GB)")
        else:
            lines.append("- (none loaded)")
    except Exception:
        lines.append("- (Ollama unreachable)")

    # open tasks
    tasks = [t for t in _load_tasks() if t.get("status") == "open"]
    lines.append(f"\n## Open tasks ({len(tasks)})")
    if tasks:
        for t in tasks[:10]:
            lines.append(f"- [{t['priority'].upper()}] {t['title']} → {t['assigned_to']}")
    else:
        lines.append("- No open tasks")

    # briefing availability
    lines.append("\n## Latest briefings")
    for prefix in ("hermes-morning-briefing", "hermes-capability-assessment"):
        p = _latest_briefing(prefix)
        if p:
            age_h = (datetime.now().timestamp() - p.stat().st_mtime) / 3600
            lines.append(f"- {prefix}: {p.name} ({age_h:.1f}h ago)")
        else:
            lines.append(f"- {prefix}: not available")

    # live BTC price
    lines.append("\n## BTC live price")
    try:
        ticker = _fetch_json("https://api.kraken.com/0/public/Ticker?pair=XXBTZUSD", timeout=5)
        lines.append(f"- BTC/USD: ${float(ticker['result']['XXBTZUSD']['c'][0]):,.2f}")
    except (KeyError, TypeError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        lines.append("- BTC/USD: unavailable")

    return "\n".join(lines)


@mcp.tool()
def get_node_diagnostic() -> str:
    """
    Run a live self-diagnostic of the HVE node stack.

    Executes hermes-diagnostic.sh which SSHes to Mercury (Pi) for real
    Lightning/LND data. Always returns live data — never cached or fabricated.

    Returns:
    - BTC/USD price (live Kraken)
    - Bitcoin node block height + sync status
    - Lightning channel count + balances (SAT only, never USD)
    - Recent payments (SAT)
    - Ollama models available on DGX Spark
    """
    script = REPO_DIR / "scripts" / "hermes-diagnostic.sh"
    if not script.exists():
        return "ERROR: hermes-diagnostic.sh not found. Cannot produce diagnostic."
    rc, output = _run(["bash", str(script)], timeout=30)
    if rc != 0 or not output.strip():
        return f"ERROR running diagnostic script (exit {rc}):\n{output}"
    return output


@mcp.tool()
def vote_backlog_issue(issue_number: int, score: int, reason: str = "", repo: str = "hanshermesagent") -> str:
    """
    Vote on a backlog issue with a score from 1 to 10.

    Posts a /score comment on the GitHub issue so rank-backlog can aggregate results.
    Call this when Hans asks you to score or vote on a backlog item.

    Args:
        issue_number: GitHub issue number to vote on (e.g. 24)
        score:        Integer score 1-10 (10 = highest priority)
        reason:       Optional brief reason for your score
        repo:         Target repo — "hanshermesagent" (default) or "mercury"

    Returns confirmation with the comment URL, or an error message.
    """
    import json as _json
    import urllib.request as _ur

    if not 1 <= score <= 10:
        return "ERROR: score must be between 1 and 10"

    if repo not in ("hanshermesagent", "mercury"):
        return "ERROR: repo must be 'hanshermesagent' or 'mercury'"

    token = None
    env_file = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_file):
        for line in open(env_file).read().splitlines():
            if line.startswith("HVE_GITHUB_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        return "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env"

    reason_str = f" — {reason}" if reason else ""
    body = f"/score {score}{reason_str}\n\n_Voted by Hermes CFO agent_"
    payload = _json.dumps({"body": body}).encode()

    req = _ur.Request(
        f"https://api.github.com/repos/humanvalueexchange/{repo}/issues/{issue_number}/comments",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read())
        return f"✅ Voted {repo}#{issue_number}: score {score}/10{reason_str} — {data['html_url']}"
    except Exception as e:
        return f"ERROR posting vote: {e}"


@mcp.tool()
def suggest_backlog_issue(title: str, hypothesis: str = "", context: str = "", direction: str = "", risks: str = "", repo: str = "hanshermesagent") -> str:
    """
    Post a research idea as a GitHub Issue to a HVE team backlog.

    Use this tool when you identify a feature idea, architectural improvement,
    or research hypothesis worth capturing. Can post to either the Hermes CFO
    backlog or the Mercury backlog — Hermes and Mercury are the team.

    Args:
        title:      Short descriptive title for the issue (required)
        hypothesis: What you believe is possible or true
        context:    Why this matters for HVE treasury or operations
        direction:  Proposed implementation approach
        risks:      Unknowns, risks, or open questions
        repo:       Target repo — "hanshermesagent" (default) or "mercury"

    Returns confirmation with the issue URL, or an error message.
    """
    import json as _json
    import urllib.request as _ur

    if repo not in ("hanshermesagent", "mercury"):
        return "ERROR: repo must be 'hanshermesagent' or 'mercury'"

    # Load token from env file
    token = None
    env_file = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_file):
        for line in open(env_file).read().splitlines():
            if line.startswith("HVE_GITHUB_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        return "ERROR: HVE_GITHUB_TOKEN not found in ~/.hermes/.env"

    # Build body from research template
    parts = []
    if hypothesis: parts.append(f"## Hypothesis\n{hypothesis}")
    if context:    parts.append(f"## Context\n{context}")
    if direction:  parts.append(f"## Proposed Direction\n{direction}")
    if risks:      parts.append(f"## Unknowns / Risks\n{risks}")
    parts.append("\n---\n*Submitted by Hermes (CFO AI agent, Human Value Exchange)*")
    body = "\n\n".join(parts) if parts else "*Submitted by Hermes CFO agent*"

    payload = _json.dumps({
        "title":  title,
        "body":   body,
        "labels": ["research", "idea"],
    }).encode()

    req = _ur.Request(
        f"https://api.github.com/repos/humanvalueexchange/{repo}/issues",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with _ur.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read())
        return f"✅ Issue #{data['number']} created in {repo}: {data['html_url']}"
    except Exception as e:
        return f"ERROR creating issue: {e}"


@mcp.tool()
def read_github_issue(issue_number: int, repo: str = "hanshermesagent") -> str:
    """
    Read a GitHub issue including its body and all comments.

    Use this when Hans asks you to review a specific issue, RFC, or ADR.
    Returns the issue title, body, state, labels, and full comment thread.
    """
    return github_read_issue(issue_number, repo)


@mcp.tool()
def comment_github_issue(issue_number: int, comment_body: str, repo: str = "hanshermesagent") -> str:
    """
    Post a comment on a GitHub issue.

    Use this to participate in RFCs, architecture reviews, and issue discussions.
    Always identify Hermes clearly in the posted comment.
    """
    return github_comment_issue(issue_number, comment_body, repo)


@mcp.tool()
def list_github_issues(repo: str = "hanshermesagent", state: str = "open", label: str = "", limit: int = 20) -> str:
    """
    List GitHub issues from a HVE repo.

    Use this to browse the backlog, find open issues in a domain, or check
    what's been recently closed.
    """
    return github_list_issues(repo, state, label, limit)


# ── Mempool.space tools ───────────────────────────────────────────────────────
mcp.tool()(_mempool_get_mempool_fees)
mcp.tool()(_mempool_get_mempool_depth)
mcp.tool()(_mempool_get_block_status)
mcp.tool()(_mempool_get_lightning_stats)


# ── A2A agent card (future-proofing) ─────────────────────────────────────────
AGENT_CARD = {
    "name": "HVE Hermes",
    "description": (
        "Hermes CFO intelligence system for Human Value Exchange. "
        "Provides BTC forecasts, mempool and Lightning intelligence, "
        "morning briefings, knowledge vault search, GitHub issue review, "
        "task management, and system context."
    ),
    "url": os.environ.get("HVE_MCP_PUBLIC_URL", "http://localhost:8765"),
    "version": "1.0.0",
    "capabilities": {
        "tools": TOOL_NAMES,
    },
}


# ── entrypoint ───────────────────────────────────────────────────────────────
def build_app():
    """
    Build the ASGI app with:
    - API key middleware
    - A2A agent card at /.well-known/agent.json
    - MCP streamable-http at /mcp (and all other paths via Mount)

    The inner FastMCP app has its own lifespan (task group for session manager).
    We delegate to it from the outer app's lifespan so it initialises correctly.
    """
    from contextlib import asynccontextmanager  # noqa: PLC0415

    from starlette.applications import Starlette  # noqa: PLC0415
    from starlette.responses import JSONResponse as JR  # noqa: PLC0415
    from starlette.routing import Mount, Route  # noqa: PLC0415

    mcp_app = mcp.http_app(transport="streamable-http")

    @asynccontextmanager
    async def lifespan(app):  # noqa: ANN001
        # Start the inner FastMCP app's lifespan (initialises the session task group)
        async with mcp_app.router.lifespan_context(app):
            yield

    async def agent_card(request: Request):
        return JR(AGENT_CARD)

    async def health(request: Request):
        return JR({"status": "ok"})

    app = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/.well-known/agent.json", agent_card),
            Route("/health", health),
            Mount("/", app=mcp_app),
        ],
    )
    app.add_middleware(APIKeyMiddleware)
    return app


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("HVE_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("HVE_MCP_PORT", "8765"))
    if host not in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("HVE_MCP_API_KEY"):
        raise SystemExit("HVE_MCP_API_KEY is required for non-local MCP binding")
    print(f"Starting HVE Hermes MCP Server on {host}:{port}")
    uvicorn.run(build_app(), host=host, port=port, log_level="info")
