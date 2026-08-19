#!/home/hans/.hermes/hermes-agent/venv/bin/python

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.knowledge import search_knowledge_vault  # noqa: E402


KNOWLEDGE_ROOT = Path("/hve-library")
MANIFEST_DIR = KNOWLEDGE_ROOT / "state" / "manifests"
DOCUMENT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


mcp = FastMCP(
    "HVE Knowledge Library",
    instructions=(
        "Read-only access to the durable HVE knowledge library. Search indexed "
        "links and PDF documents or retrieve extracted text for a known document ID."
    ),
)


def _run(command: list[str], timeout: int) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = completed.stdout.strip()
    if completed.returncode != 0 and completed.stderr.strip():
        output = completed.stderr.strip()
    return completed.returncode, output


@mcp.tool()
def search_link_library(query: str, max_results: int = 5) -> str:
    """Search archived links and indexed PDF documents by meaning or keywords."""
    query = query.strip()
    if not query:
        return "Query must not be empty."
    return search_knowledge_vault(query, max_results, _run)


@mcp.tool()
def read_link_document(document_id: str, max_chars: int = 12000) -> dict[str, Any]:
    """Read metadata and extracted text for one archived link or PDF document."""
    document_id = document_id.strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(document_id):
        return {"status": "invalid_document_id", "error": "Expected a 16-character hexadecimal document ID."}

    manifest_path = MANIFEST_DIR / f"{document_id}.json"
    if not manifest_path.is_file():
        return {"status": "not_found", "document_id": document_id}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    text_path = Path(manifest.get("extracted_text_path", ""))
    text = text_path.read_text(encoding="utf-8") if text_path.is_file() else ""
    safe_max_chars = max(1, min(int(max_chars), 50000))
    return {
        "status": "ok",
        "document_id": document_id,
        "title": manifest.get("title"),
        "canonical_url": manifest.get("canonical_url"),
        "capture_context": [item.get("capture_context") for item in manifest.get("captures", [])],
        "captured_at": manifest.get("captured_at"),
        "indexed": manifest.get("status") == "indexed",
        "text": text[:safe_max_chars],
        "truncated": len(text) > safe_max_chars,
    }


@mcp.tool()
def list_recent_links(hours: int = 24, max_results: int = 50) -> list[dict[str, Any]]:
    """List links captured within the requested number of recent hours."""
    safe_hours = max(1, min(int(hours), 24 * 30))
    safe_max_results = max(1, min(int(max_results), 200))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)
    results: list[dict[str, Any]] = []

    for manifest_path in MANIFEST_DIR.glob("*.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("source_type") != "web_link":
            continue

        recent_captures = []
        for capture in manifest.get("captures", []):
            if not isinstance(capture, dict):
                continue
            captured_at = capture.get("captured_at")
            try:
                captured_time = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if captured_time >= cutoff:
                recent_captures.append(capture)
        if not recent_captures:
            continue

        latest = max(recent_captures, key=lambda item: str(item.get("captured_at", "")))
        results.append(
            {
                "document_id": manifest.get("document_id"),
                "title": manifest.get("title"),
                "canonical_url": manifest.get("canonical_url"),
                "captured_at": latest.get("captured_at"),
                "capture_context": latest.get("capture_context"),
                "recent_capture_count": len(recent_captures),
                "indexed": manifest.get("status") == "indexed",
                "index_status": manifest.get("index_status"),
                "chunk_count": manifest.get("chunk_count", 0),
                "manifest_path": str(manifest_path),
            }
        )

    results.sort(key=lambda item: str(item.get("captured_at", "")), reverse=True)
    return results[:safe_max_results]


if __name__ == "__main__":
    mcp.run(transport="stdio")
