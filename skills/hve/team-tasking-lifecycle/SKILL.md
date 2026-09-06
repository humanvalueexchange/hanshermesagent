---
name: team-tasking-lifecycle
description: "Preserve pilot task state across every lifecycle turn."
category: hve
version: 1.0
date: 2026-09-05
---

# team-tasking-lifecycle — Deterministic Phase 0 transitions

Use this skill to keep a private pilot task on one explicit state path.

## State discipline

Maintain one working record containing the task ID, current state, owner,
deliverable, and last confirmed event. Update it only from a confirmed MCP
response or an audit-trail result.

Allowed sequence:

`draft → open → in_progress → blocked → in_progress → awaiting_validation → done`

An artifact delivery may move `open` or `in_progress` to
`awaiting_validation`. A completion report may also move `open` or
`in_progress` to `awaiting_validation`. Hans rejection moves
`awaiting_validation` back to `open` with an explicit reason.

## Recovery rules

- If a tool rejects an operation, do not claim progress and do not change the
  recorded state.
- If the failure is a missing or malformed argument, correct the argument
  before retrying; do not repeat the same invalid call.
- If the backend reports a duplicate event or artifact, treat the operation as
  already applied and reconcile with `task_audit_trail`.
- Never approve, validate, reject, or close a task based on Hermes's own text.
  Those actions require an explicit Hans message in the personal DM.
- After `awaiting_validation`, wait for Hans's explicit approval or rejection.
