#!/home/hans/.hermes-mcp-venv/bin/python

"""MCP boundary for the private Hans-only Phase 0 tasking pilot."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.team_tasking_pilot import PilotError, default_store  # noqa: E402


mcp = FastMCP(
    "HVE Private Team Tasking Pilot",
    instructions=(
        "Hans-only Phase 0 private workflow. This MCP server writes only to the "
        "isolated local pilot backend. It never creates GitHub objects, commits, "
        "public artifacts, or WhatsApp group messages."
    ),
)


def _call(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except PilotError as exc:
        return {"status": "rejected", "confirmed": False, "error": str(exc)}


@mcp.tool()
def normalize_task(
    source_message_id: str,
    source_message: str,
    owner: str,
    deliverable: str,
    pillar: str,
    acceptance_criteria: list[str],
    due_date: str | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize an explicit Hans proposal and return a preview without creating an external object."""
    return _call(
        default_store().normalize,
        source_message_id=source_message_id,
        source_message=source_message,
        owner=owner,
        deliverable=deliverable,
        pillar=pillar,
        due_date=due_date,
        acceptance_criteria=acceptance_criteria,
        risks=risks,
    )


@mcp.tool()
def approve_task(task_id: str, approval_message_id: str) -> dict[str, Any]:
    """Approve one preview and create its local private pilot card in Open state."""
    return _call(default_store().approve, task_id, approval_message_id=approval_message_id)


@mcp.tool()
def starting(task_id: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Record a starting update and move an approved task to In Progress."""
    return _call(default_store().starting, task_id, source_message=source_message, event_id=event_id)


@mcp.tool()
def blocked(task_id: str, reason: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Record a blocker and preserve the exact reason for recovery."""
    return _call(default_store().block, task_id, reason=reason, source_message=source_message, event_id=event_id)


@mcp.tool()
def retry(task_id: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Retry a blocked task after its underlying blocker is resolved."""
    return _call(default_store().retry, task_id, source_message=source_message, event_id=event_id)


@mcp.tool()
def deliver_artifact(
    task_id: str,
    filename: str,
    content_base64: str,
    source_message: str,
    event_id: str,
) -> dict[str, Any]:
    """Store a private pilot artifact and move the task to Awaiting Validation."""
    try:
        content = base64.b64decode(content_base64, validate=True)
    except Exception as exc:
        return {"status": "rejected", "confirmed": False, "error": f"invalid base64 artifact: {exc}"}
    return _call(
        default_store().deliver_artifact,
        task_id,
        filename=filename,
        content=content,
        source_message=source_message,
        event_id=event_id,
    )


@mcp.tool()
def report_done(task_id: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Record a completion report and move the task to Awaiting Validation."""
    return _call(default_store().report_done, task_id, source_message=source_message, event_id=event_id)


@mcp.tool()
def validate_task(
    task_id: str,
    approved: bool,
    source_message: str,
    event_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Record Hans validation; rejection returns the task to Open with its reason."""
    return _call(
        default_store().validate,
        task_id,
        approved=approved,
        source_message=source_message,
        event_id=event_id,
        reason=reason,
    )


@mcp.tool()
def record_failure(task_id: str, action: str, error: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Surface a failed underlying operation with its exact pending action and recovery state."""
    return _call(
        default_store().failure,
        task_id,
        action=action,
        error=error,
        source_message=source_message,
        event_id=event_id,
    )


@mcp.tool()
def task_status_digest() -> dict[str, Any]:
    """Return the ownership and due-date digest grouped by lifecycle state."""
    return default_store().digest()


@mcp.tool()
def task_audit_trail(task_id: str) -> dict[str, Any]:
    """Return the immutable event trail for one pilot task."""
    try:
        return {"status": "ok", "task_id": task_id, "events": default_store().events(task_id)}
    except PilotError as exc:
        return {"status": "rejected", "error": str(exc)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
