#!/home/hans/.hermes-mcp-venv/bin/python

from __future__ import annotations

import fcntl
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP


LEDGER_PATH = Path(
    "/home/hans/.hermes/profiles/hanshermesagent/state/weekly-decision-log.jsonl"
)
MEMORY_DB_PATH = Path(
    "/home/hans/.hermes/profiles/hanshermesagent/local-memory.db"
)
DECISION_ID_RE = re.compile(r"^D-\d{4}-\d{2}-\d{2}-\d{2,}$")
EVENT_TYPES = {
    "created",
    "confirmed",
    "updated",
    "completed",
    "deferred",
    "rejected",
    "cancelled",
    "blocked",
}
STATUSES = {
    "open",
    "approved",
    "in_progress",
    "completed",
    "deferred",
    "rejected",
    "cancelled",
    "blocked",
    "needs_clarification",
}

mcp = FastMCP(
    "HVE Decision Ledger",
    instructions=(
        "Authorized append-only persistence for Hans's confirmed HVE decisions. "
        "This server exposes no shell or arbitrary filesystem operations."
    ),
)


def _validate_event(event: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(event, dict):
        return None, "Each event must be an object."
    decision_id = event.get("decision_id")
    if not isinstance(decision_id, str) or not DECISION_ID_RE.fullmatch(decision_id):
        return None, f"Invalid decision_id: {decision_id!r}."
    status = event.get("status")
    if status not in STATUSES:
        return None, f"Invalid status: {status!r}."
    normalized = dict(event)
    event_type = normalized.setdefault("event_type", "created")
    if event_type not in EVENT_TYPES:
        return None, f"Invalid event_type: {event_type!r}."
    normalized.setdefault("decision_text", normalized.get("summary"))
    normalized.setdefault("event_at", normalized.get("recorded_utc"))
    normalized.setdefault("source_channel_scope", "dm")
    if not normalized.get("decision_text"):
        return None, f"Missing decision_text for {decision_id}."
    return normalized, None


def _event_id(event: dict[str, Any], index: int) -> str:
    supplied = event.get("event_id")
    if isinstance(supplied, str) and supplied.strip():
        return supplied
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"DLE-{timestamp}-{index:03d}"


@mcp.tool()
def append_decision_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Append confirmed decision events to the fixed HVE decision ledger."""
    if not events:
        return {"status": "invalid", "error": "At least one event is required."}

    validated: list[dict[str, Any]] = []
    for index, raw_event in enumerate(events, 1):
        event, error = _validate_event(raw_event)
        if error:
            return {"status": "invalid", "error": error, "event_index": index}
        assert event is not None
        event["event_id"] = _event_id(event, index)
        event.setdefault("event_at", datetime.now(timezone.utc).isoformat())
        event.setdefault("source_channel_scope", "dm")
        validated.append(event)

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a+", encoding="utf-8") as ledger:
        fcntl.flock(ledger.fileno(), fcntl.LOCK_EX)
        for event in validated:
            ledger.write(json.dumps(event, ensure_ascii=True, sort_keys=True) + "\n")
        ledger.flush()
        os.fsync(ledger.fileno())
        fcntl.flock(ledger.fileno(), fcntl.LOCK_UN)

    return {
        "status": "appended",
        "path": str(LEDGER_PATH),
        "event_count": len(validated),
        "decision_ids": [event["decision_id"] for event in validated],
    }


@mcp.tool()
def list_decision_events(
    decision_ids: list[str] | None = None,
    statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Read decision-ledger events, optionally filtered by ID or status."""
    if not LEDGER_PATH.is_file():
        return []
    wanted_ids = set(decision_ids or [])
    wanted_statuses = set(statuses or [])
    results: list[dict[str, Any]] = []
    with LEDGER_PATH.open("r", encoding="utf-8") as ledger:
        for line_number, line in enumerate(ledger, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed ledger line {line_number}: {exc}") from exc
            if wanted_ids and event.get("decision_id") not in wanted_ids:
                continue
            if wanted_statuses and event.get("status") not in wanted_statuses:
                continue
            results.append(event)
    return results


@mcp.tool()
def list_ledger_handoff_candidates(limit: int = 50) -> list[dict[str, Any]]:
    """Read SQLite decision/policy proposals awaiting Hans's confirmation."""
    if not MEMORY_DB_PATH.is_file():
        return []
    with sqlite3.connect(MEMORY_DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT handoff_id, report_id, job_id, source_id, candidate_index,
                   candidate_json, decision_text, status, created_at, updated_at
            FROM ledger_handoffs
            WHERE status='pending_confirmation'
            ORDER BY handoff_id
            LIMIT ?
            """,
            (max(1, min(int(limit), 200)),),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["candidate"] = json.loads(item.pop("candidate_json"))
        results.append(item)
    return results


if __name__ == "__main__":
    mcp.run(transport="stdio")
