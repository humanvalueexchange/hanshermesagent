# HVE Team Tasking — Phase 0 Private Pilot

**Date:** 2026-09-05  
**Status:** Implemented; awaiting Hans's personal validation  
**Scope:** Hans's personal WhatsApp DM only

## Isolated backend decision

Phase 0 uses `tools/team_tasking_pilot.py` with a local SQLite database at:

```text
~/.hermes/profiles/hanshermesagent/state/team-tasking-pilot.db
```

Private pilot artifacts are written below the adjacent
`team-tasking-pilot-artifacts/` directory. The MCP boundary is
`mcp/team_tasking_pilot_server.py`, configured through the repository-managed
Hermes template.

This backend intentionally does **not** call GitHub, create issues or Project
cards, commit files, write to `humanvalueexchange/hve-team`, or send WhatsApp
messages. It returns card and team-message previews only; the native skill
requires explicit Hans approval before the local pilot card changes from
`draft` to `open`.

## Safety and provenance

- Task IDs are deterministic from the source message ID (`P0-...`).
- SQLite uniqueness constraints and event keys make retries idempotent.
- Events are append-only and retain source message, actor, timestamp, task ID,
  requested transition, result, and approval/rejection reason.
- Artifacts are stored only in the isolated pilot directory and are recorded
  with SHA-256 hashes.
- Financial, health, tax, strategic, credential, and restricted content is
  classified and marked as blocked for any future public-repository adapter.
- AL-01 and Alan's bio are reserved and rejected during Phase 0.
- Failed operations return the exact pending action and recovery state.

The backend is a control-plane test surface, not an authorization to proceed
to the public team repository or controlled group test. Those require Hans's
explicit Phase 0 approval after the private DM round trip passes.

## Hans manual DM script

Run these as separate messages in the existing personal DM, replacing
`<task-id>` with the ID returned in the preview:

```text
Propose a private pilot task: prepare a public onboarding checklist.
Owner: Hermes
Pillar: Time
Due: 2026-09-12
Acceptance: Markdown checklist; every step has an owner.
Risks: do not include credentials.
```

Expected: Hermes asks for or confirms explicit fields, then shows the stable
ID, card preview, team-message preview, sensitivity, and `Open` as the intended
state. No GitHub or group action exists yet.

```text
Approve exactly this task: <task-id>
Starting <task-id>
Blocked <task-id> — waiting for source material
Retry <task-id>
Deliver `checklist.md` for <task-id> with the approved checklist content
Hans rejects <task-id> — add the missing evidence link
Retry <task-id>
Hans approves <task-id>
Status digest
Audit trail <task-id>
```

Expected: the card proceeds through `Open`, `In Progress`, `Blocked`,
`In Progress`, and `Awaiting Validation`; rejection records its reason and
returns to `Open`; the final approval reaches `Done`. The digest and audit
trail must match the DM sequence. Repeat any message once to confirm no
duplicate card, artifact, or transition is reported.

Also test a proposal containing financial, health, tax, strategic, or
credential content. It may be classified in the private pilot, but its card
must show `blocked_by_sensitivity_gate` for any future public repository
adapter. Do not test AL-01 or send any group message.
