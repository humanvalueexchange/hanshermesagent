---
name: team-tasking-pilot
description: "Hans-only Phase 0 private tasking and delivery workflow."
category: hve
version: 1.0
date: 2026-09-05
---

# team-tasking-pilot — Private Phase 0 DM workflow

This skill is limited to Hans's personal WhatsApp DM. It is a control-plane
adapter, not an autonomous project manager.

## Hard boundaries

- Never create `humanvalueexchange/hve-team`, a GitHub Project, a public issue,
  a commit, or a group message during Phase 0.
- Never assign AL-01 or Alan's bio.
- Never infer an owner, due date, scope change, approval, completion, or
  rejection from ambiguous text. Ask for the missing explicit value.
- Treat `hve-cfo` as a separate profile; do not route financial or trading
  runtime work to this profile.
- Telegram is disabled for `hanshermesagent`.

## DM interaction

1. Call `normalize_task` only after the proposal has explicit owner,
   deliverable, Five Wealth pillar, acceptance criteria, and optional due date.
2. Show the returned task ID, card preview, team-message preview, sensitivity
   classification, and intended initial state (`Open`). Do not claim that
   anything was created.
3. Call `approve_task` only after Hans explicitly approves that exact preview.
4. Use `starting`, `blocked`, `retry`, `deliver_artifact`, and `report_done` for
   simulated lifecycle reports. Artifact content is stored only in the private
   pilot backend.
5. Use `validate_task` only for Hans's explicit approval or rejection. A
   rejection must include the exact reason and returns the task to `Open`.
6. Use `task_status_digest` and `task_audit_trail` to show current ownership,
   due dates, states, and provenance.

Every successful reply must be based on the tool's `confirmed` result. On a
failure, surface the exact `pending_action`, error, and recovery state without
reporting success.
