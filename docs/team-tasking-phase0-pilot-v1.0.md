# HVE Team Tasking — Phase 0 Private Pilot

**Date:** 2026-09-05  
**Status:** Implemented with UAT hardening; clean Phase 0 UAT not yet passed
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
  with filename, byte count, line count, SHA-256 hash, and final state
  metadata.
- Financial, health, tax, strategic, credential, and restricted content is
  classified and marked as blocked for any future public-repository adapter.
- AL-01 and Alan's bio are reserved and rejected during Phase 0.
- Failed operations return the exact pending action and recovery state.

The backend is a control-plane test surface, not an authorization to proceed
to the public team repository or controlled group test. Those require Hans's
explicit Phase 0 approval after the private DM round trip passes.

## Artifact delivery contract

Use `deliver_text_artifact` for inline Markdown, JSON, or other UTF-8 text.
Hermes passes the text as `content_text`; the MCP server performs UTF-8 byte
handling and stores the resulting bytes. This avoids model-side Base64 mistakes
for normal text deliverables.

Use `deliver_artifact` only when a payload must remain binary-safe. Its
existing contract is preserved: callers pass standard Base64 in
`content_base64`, and the server decodes it with strict Base64 validation before
writing the bytes.

Both delivery tools return:

- `filename`
- `byte_count`
- `line_count`
- `sha256`
- `final_state`
- `awaiting_validation`

After `confirmed: true` artifact delivery, Hermes must report those fields and
stop. It must not call `report_done`, `validate_task`, terminal, browser/web,
or unrelated tools in that same turn. The repository can enforce the valid
state transition (`open`/`in_progress` → `awaiting_validation`) and can provide
tool-response/profile guardrails, but it cannot prove a framework-level
same-turn hard stop without runtime orchestration support. The clean UAT
profile therefore removes the risky tools for the delivery run instead of
pretending the repository alone can enforce that runtime guarantee.

## Clean UAT profile configuration

`config/hermes-config.phase0-uat.yaml` is the narrow clean-delivery UAT profile
configuration. It keeps the required 64K model context
(`context_length: 65536` and `ollama_num_ctx: 65536`) while narrowing the
WhatsApp tool surface to non-terminal coordination tools and the private pilot
MCP server. It also lists the excluded high-risk toolsets in
`agent.disabled_toolsets`.

For the clean UAT, the profile intentionally excludes:

- terminal
- browser/web
- code execution, delegation, cron, and computer-use tools
- unrelated MCP servers such as shared context and HVE node tools

The profile exposes the complete approved private pilot lifecycle on
`hve-team-tasking-pilot`: `normalize_task`, `approve_task`, `starting`,
`blocked`, `retry`, `deliver_text_artifact`, `deliver_artifact`, `report_done`,
`validate_task`, `record_failure`, `task_status_digest`, and
`task_audit_trail`. Operational discipline still requires the delivery turn to
stop at `awaiting_validation`; `validate_task` is only for a later explicit Hans
approval or rejection turn.

Activating this profile modifies the live Hermes profile outside this
repository, so activation must be performed as an explicit deployment action
after the committed source is reviewed.

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
```

Expected: the card proceeds through `Open`, `In Progress`, `Blocked`,
`In Progress`, and `Awaiting Validation`. Hermes reports the artifact filename,
byte count, line count, SHA-256, and `awaiting_validation`, then stops. Repeat
the delivery message once to confirm the retry reports a duplicate/idempotent
delivery without creating another artifact.

Validation remains Hans-gated. Do not ask Hermes to approve or reject the task
inside the same delivery turn. After a separate explicit Hans validation
message, the sequence is:

```text
Hans rejects <task-id> — add the missing evidence link
Retry <task-id>
Hans approves <task-id>
Status digest
Audit trail <task-id>
```

Expected: rejection records its reason and returns to `Open`; the final
explicit Hans approval reaches `Done`. The digest and audit trail must match
the DM sequence. Repeat any message once to confirm no duplicate card,
artifact, or transition is reported.

Also test a proposal containing financial, health, tax, strategic, or
credential content. It may be classified in the private pilot, but its card
must show `blocked_by_sensitivity_gate` for any future public repository
adapter. Do not test AL-01 or send any group message.

## Operating skills

The repository provides four companion skills:

- `team-tasking-mcp-discipline` — exact named-tool calls, complete arguments,
  stable task IDs, and confirmed-response handling.
- `team-tasking-artifact-delivery` — UTF-8/Base64 encoding, safe filenames,
  private artifact handling, and binary-file boundaries.
- `team-tasking-lifecycle` — valid state transitions, explicit Hans gates, and
  deterministic recovery.
- `team-tasking-pilot` — the Hans-only Phase 0 DM workflow and clean UAT
  boundary.

Live UAT evidence is runtime-local and must not be committed to GitHub. The
Phase 0 gate remains closed until one clean personal-DM run completes without
manual recovery, path correction, duplicate intervention, or ambiguous
success reporting.
