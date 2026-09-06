#!/home/hans/.hermes-mcp-venv/bin/python

"""MCP boundary for the gated Phase 1 Hans-only GitHub UAT."""

from __future__ import annotations

import base64
import binascii
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.github_phase1 import GitHubPhase1Adapter, GitHubPhase1Error  # noqa: E402
from tools.team_tasking_pilot import PilotError, PilotStore  # noqa: E402


mcp = FastMCP(
    "HVE Controlled Phase 1 GitHub Tasking",
    instructions=(
        "Hans-only WhatsApp DM Phase 1. The local SQLite state machine remains "
        "authoritative. GitHub writes are public, explicit, approval-gated, "
        "idempotent, and limited to humanvalueexchange/hve-team Project 2. "
        "Never publish non-public content. After artifact publication, report "
        "the confirmed path and commit SHA and stop for Hans validation."
    ),
)


def _store() -> PilotStore:
    return PilotStore(
        os.environ.get(
            "HVE_TEAM_PHASE1_DB",
            "~/.hermes/profiles/hanshermesagent/state/team-tasking-phase1.db",
        ),
        task_prefix="P1",
        backend_name="controlled-phase-1-github",
        public_repository="humanvalueexchange/hve-team",
    )


def _adapter() -> GitHubPhase1Adapter:
    return GitHubPhase1Adapter()


def _call(function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except (PilotError, GitHubPhase1Error) as exc:
        return {"status": "rejected", "confirmed": False, "error": str(exc)}


def _task_payload(result: dict[str, Any]) -> dict[str, Any]:
    card = result["card"]
    return {
        "task_id": result["task_id"],
        "source_message": card.get("source_message", ""),
        "deliverable": card["deliverable"],
        "acceptance_criteria": card["acceptance_criteria"],
        "risks": card["risks"],
        "owner": card["owner"],
        "pillar": card["pillar"],
        "due_date": card.get("due_date"),
        "sensitivity": result["sensitivity"],
    }


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
    """Create a local draft preview only; no GitHub object is written."""
    return _call(
        _store().normalize,
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
    """Approve one preview, then create exactly one GitHub issue and Project item."""
    store = _store()
    result = store.approve(task_id, approval_message_id=approval_message_id)
    try:
        tracking = _adapter().create_tracking_record(_task_payload(result), approved=True)
    except GitHubPhase1Error as exc:
        return store.failure(
            task_id,
            action="create GitHub tracking record",
            error=str(exc),
            source_message=approval_message_id,
            event_id=f"{approval_message_id}:github",
        )
    result.update({"github": tracking, "project_item_id": tracking["project_item_id"]})
    return result


@mcp.tool()
def starting(task_id: str, project_item_id: str, source_message: str, event_id: str) -> dict[str, Any]:
    """Move local state to In Progress and confirm the Project status."""
    store = _store()
    result = store.starting(task_id, source_message=source_message, event_id=event_id)
    try:
        status = _adapter().set_status(project_item_id, "in_progress")
    except GitHubPhase1Error as exc:
        return store.failure(
            task_id,
            action="set GitHub Project status In Progress",
            error=str(exc),
            source_message=source_message,
            event_id=f"{event_id}:github",
        )
    result["github"] = status
    return result


@mcp.tool()
def deliver_text_artifact(
    task_id: str,
    project_item_id: str,
    filename: str,
    content_text: str,
    source_message: str,
    event_id: str,
) -> dict[str, Any]:
    """Store the artifact locally, publish it once, then await Hans validation."""
    if not isinstance(content_text, str):
        return {"status": "rejected", "confirmed": False, "error": "content_text must be text"}
    store = _store()
    result = store.deliver_text_artifact(
        task_id,
        filename=filename,
        content_text=content_text,
        source_message=source_message,
        event_id=event_id,
    )
    try:
        published = _adapter().publish_artifact(
            _task_payload(result),
            project_item_id=project_item_id,
            filename=filename,
            content=content_text.encode("utf-8"),
            approved=True,
        )
    except GitHubPhase1Error as exc:
        return store.failure(
            task_id,
            action="publish GitHub artifact",
            error=str(exc),
            source_message=source_message,
            event_id=f"{event_id}:github",
        )
    result["github"] = published
    result["operating_contract"] = (
        "Report the confirmed artifact path and commit SHA, then stop for Hans validation."
    )
    return result


@mcp.tool()
def deliver_artifact(
    task_id: str,
    project_item_id: str,
    filename: str,
    content_base64: str,
    source_message: str,
    event_id: str,
) -> dict[str, Any]:
    """Decode one binary-safe artifact and delegate to the same guarded publisher."""
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        return {"status": "rejected", "confirmed": False, "error": f"invalid base64 artifact: {exc}"}
    store = _store()
    result = store.deliver_artifact(
        task_id,
        filename=filename,
        content=content,
        source_message=source_message,
        event_id=event_id,
    )
    try:
        published = _adapter().publish_artifact(
            _task_payload(result),
            project_item_id=project_item_id,
            filename=filename,
            content=content,
            approved=True,
        )
    except GitHubPhase1Error as exc:
        return store.failure(
            task_id,
            action="publish GitHub artifact",
            error=str(exc),
            source_message=source_message,
            event_id=f"{event_id}:github",
        )
    result["github"] = published
    return result


@mcp.tool()
def validate_task(
    task_id: str,
    project_item_id: str,
    approved: bool,
    source_message: str,
    event_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Require Hans's explicit validation before moving the public item to Done."""
    store = _store()
    result = store.validate(
        task_id,
        approved=approved,
        source_message=source_message,
        event_id=event_id,
        reason=reason,
    )
    try:
        status = _adapter().set_status(project_item_id, "done" if approved else "open")
    except GitHubPhase1Error as exc:
        return store.failure(
            task_id,
            action=f"set GitHub Project status {'Done' if approved else 'Open'}",
            error=str(exc),
            source_message=source_message,
            event_id=f"{event_id}:github",
        )
    result["github"] = status
    return result


@mcp.tool()
def task_status_digest() -> dict[str, Any]:
    """Return the local authoritative Phase 1 task digest."""
    return _store().digest()


@mcp.tool()
def task_audit_trail(task_id: str) -> dict[str, Any]:
    """Return the local append-only Phase 1 audit trail."""
    return _call(lambda: {"status": "ok", "task_id": task_id, "events": _store().events(task_id)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
