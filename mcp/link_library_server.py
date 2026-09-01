#!/home/hans/.hermes/hermes-agent/venv/bin/python

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.knowledge import search_knowledge_vault_machine  # noqa: E402
from tools.knowledge_layer_client import cli_environment, run_cli  # noqa: E402
from tools.library_annotations import (  # noqa: E402
    AnnotationError,
    append_annotation,
    read_annotations,
)


KNOWLEDGE_ROOT = Path("/hve-library")
MANIFEST_DIR = KNOWLEDGE_ROOT / "state" / "manifests"
DOCUMENT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


mcp = FastMCP(
    "HVE Knowledge Library",
    instructions=(
        "Access the durable HVE knowledge library. Search indexed links and PDF "
        "documents, retrieve extracted text for a known document ID, and append "
        "authorized provenance annotations without altering original artifacts."
    ),
)


def _run(command: list[str], timeout: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=cli_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        detail = str(exc)
        return 124, f"knowledge-layer command timed out: {detail}"
    except (FileNotFoundError, OSError) as exc:
        return 127, f"knowledge-layer command could not start: {exc}"
    output = completed.stdout.strip()
    if completed.returncode != 0 and completed.stderr.strip():
        output = completed.stderr.strip()
    return completed.returncode, output


@mcp.tool()
def search_link_library(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search archived links and indexed PDF documents by meaning or keywords."""
    query = query.strip()
    if not query:
        return {
            "retrieval_mode": "invalid",
            "semantic_available": False,
            "fallback_used": False,
            "backend_error": "Query must not be empty.",
            "results": [],
        }
    return search_knowledge_vault_machine(query, max_results, _run)


@mcp.tool()
def read_link_document(document_id: str, max_chars: int = 12000) -> dict[str, Any]:
    """Read metadata and extracted text for one archived link or PDF document."""
    document_id = document_id.strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(document_id):
        return {"status": "invalid_document_id", "error": "Expected a 16-character hexadecimal document ID."}

    safe_max_chars = max(1, min(int(max_chars), 50000))
    completed = run_cli(["document", document_id, "--max-chars", str(safe_max_chars)])
    if completed.returncode != 0:
        if "manifest not found" in completed.stderr.lower():
            return {"status": "not_found", "document_id": document_id}
        return {
            "status": "error",
            "document_id": document_id,
            "error": (completed.stderr or completed.stdout).strip(),
        }
    payload = json.loads(completed.stdout)
    manifest = payload["manifest"]
    text = payload["text"]
    return {
        "status": "ok",
        "document_id": document_id,
        "sha256": manifest.get("sha256"),
        "title": manifest.get("title"),
        "source_path": manifest.get("source_path"),
        "manifest_path": manifest.get("_manifest_path"),
        "chunk_count": manifest.get("chunk_count", 0),
        "video_id": manifest.get("video_id"),
        "canonical_url": manifest.get("canonical_url"),
        "capture_context": [item.get("capture_context") for item in manifest.get("captures", [])],
        "captured_at": manifest.get("captured_at"),
        "indexed": (
            manifest.get("status") == "indexed"
            or manifest.get("index_status") == "completed"
        ),
        "transcript_status": manifest.get("transcript_status"),
        "transcript_path": manifest.get("transcript_path"),
        "annotations": read_annotations(document_id),
        "text": text[:safe_max_chars],
        "truncated": payload["truncated"],
        "validation_status": "validated",
    }


@mcp.tool()
def read_link_document_chunks(
    document_id: str,
    start_chunk: int = 0,
    max_chunks: int = 10,
) -> dict[str, Any]:
    """Read a bounded, provenance-preserving page of document chunks."""
    document_id = document_id.strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(document_id):
        return {
            "status": "invalid_document_id",
            "error": "Expected a 16-character hexadecimal document ID.",
        }
    try:
        safe_start = max(0, min(int(start_chunk), 1_000_000))
        safe_max = max(1, min(int(max_chunks), 10))
    except (TypeError, ValueError):
        return {"status": "invalid_pagination", "document_id": document_id}
    completed = run_cli(
        [
            "document-chunks",
            document_id,
            "--start-chunk",
            str(safe_start),
            "--max-chunks",
            str(safe_max),
        ]
    )
    if completed.returncode != 0:
        return {
            "status": "error",
            "document_id": document_id,
            "error": (completed.stderr or completed.stdout).strip(),
        }
    payload = json.loads(completed.stdout)
    payload["status"] = "ok"
    return payload


@mcp.tool()
def annotate_record(
    document_id: str,
    annotation: str,
    classification: str = "provenance",
    verification_status: str = "owner_attested",
    authority: str = "Hans Westphal",
    evidence: str | None = None,
) -> dict[str, Any]:
    """Append an authorized, provenance-bearing annotation to an existing record."""
    try:
        return append_annotation(
            document_id,
            annotation,
            classification,
            verification_status,
            authority,
            evidence,
        )
    except AnnotationError as exc:
        return {
            "status": "rejected",
            "document_id": str(document_id).strip().lower(),
            "error": str(exc),
        }


@mcp.tool()
def list_record_annotations(document_id: str) -> dict[str, Any]:
    """List append-only annotations for one archived record."""
    normalized = document_id.strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(normalized):
        return {"status": "invalid_document_id", "error": "Expected a 16-character hexadecimal document ID."}
    manifest_path = MANIFEST_DIR / f"{normalized}.json"
    if not manifest_path.is_file():
        return {"status": "not_found", "document_id": normalized}
    return {
        "status": "ok",
        "document_id": normalized,
        "annotations": read_annotations(normalized),
    }


@mcp.tool()
def list_recent_links(hours: int = 24, max_results: int = 50) -> list[dict[str, Any]]:
    """List links captured within the requested number of recent hours."""
    safe_hours = max(1, min(int(hours), 24 * 30))
    safe_max_results = max(1, min(int(max_results), 200))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=safe_hours)
    completed = run_cli(["documents"])
    if completed.returncode != 0:
        return []
    manifests = json.loads(completed.stdout)
    results: list[dict[str, Any]] = []

    for manifest in manifests:
        manifest_path = Path(manifest["_manifest_path"])
        if not isinstance(manifest, dict) or manifest.get("source_type") not in {"web_link", "youtube_video"}:
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
                "video_id": manifest.get("video_id"),
                "canonical_url": manifest.get("canonical_url"),
                "captured_at": latest.get("captured_at"),
                "capture_context": latest.get("capture_context"),
                "recent_capture_count": len(recent_captures),
                "indexed": manifest.get("status") == "indexed",
                "transcript_status": manifest.get("transcript_status"),
                "index_status": manifest.get("index_status"),
                "chunk_count": manifest.get("chunk_count", 0),
                "manifest_path": str(manifest_path),
            }
        )

    results.sort(key=lambda item: str(item.get("captured_at", "")), reverse=True)
    return results[:safe_max_results]


if __name__ == "__main__":
    mcp.run(transport="stdio")
