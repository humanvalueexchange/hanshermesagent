# HVE Team Tasking - Phase 1 GitHub UAT Contract

**Status:** Implemented; live UAT not run
**Scope:** Hans-owned, WhatsApp-only, public-safe task delivery

## Fixed public control surface

- Repository: `humanvalueexchange/hve-team`
- Default branch: `main`
- Project: `humanvalueexchange/HVE Team Delivery` (`2`)
- Project URL: `https://github.com/orgs/humanvalueexchange/projects/2`
- Project status order: `Open`, `In Progress`, `Awaiting Validation`, `Done`

The local SQLite state machine remains authoritative. The GitHub adapter is an
explicit side-effect boundary used only by
`mcp/team_tasking_phase1_server.py`. The Phase 0 MCP server and database are
unchanged.

## Identity and idempotency contract

| Field | Contract |
| --- | --- |
| Hans/source message ID | Required WhatsApp message identifier |
| Task ID | `P1-` plus the first 12 uppercase SHA-256 characters of the source message ID |
| Lifecycle event ID | `P1E-` plus the first 16 uppercase SHA-256 characters of `source_message_id:action` |
| Tracking record | One GitHub issue titled with `[HVE-TASK <task-id>]` |
| Project item | One item linked to that issue; its returned item ID is carried explicitly |
| Artifact path | `artifacts/<task-id>/<safe-filename>` on `main` |
| Artifact commit | One GitHub Contents API commit; an existing path is never overwritten |
| Idempotency key | Task ID for the record, event ID for each lifecycle action, and task/path/content hash for an artifact |
| Public fields | Owner, Pillar, Due date, Sensitivity, and Task ID are written to the Project item |

Only `public` content owned by Hans is eligible. The adapter re-runs the
sensitivity classifier over the request, acceptance criteria, risks, and
artifact bytes before every public write.

## Side-effect and retry behavior

- Normalization performs no GitHub write.
- Approval is required before issue, Project item, or artifact creation.
- Issue and Project item lookup occurs before creation; retries reconcile to the
  existing exact task marker instead of creating another object.
- Existing artifact content is compared by bytes. Equal content is reported as
  a duplicate; different content fails visibly without overwrite.
- A missing or malformed GitHub response, unavailable authentication,
  repository, Project, or field causes a visible failure. No success-shaped
  fallback is returned.
- Local state transitions remain authoritative. If an external mutation fails
  after a local transition, the MCP call fails visibly and the local audit trail
  preserves the confirmed local state for explicit recovery.
- Status mapping is `open -> Open`, `in_progress -> In Progress`,
  `awaiting_validation -> Awaiting Validation`, and `done -> Done`.
- Validation rejection maps the local task and Project item back to `Open` with
  Hans's explicit reason.
- The adapter never marks `Done` before the separate Hans validation call.

## Runtime boundary

`config/hermes-config.phase1-uat.yaml` is a separate activation artifact. It
keeps 65536-token context, enables WhatsApp, disables Telegram, and exposes
only the Phase 1 MCP server. Terminal, browser, web, delegation, cron,
code-execution, computer-use, group broadcast, and unrelated MCP surfaces
remain disabled. The live Phase 0 configuration must be backed up before any
activation and restored if activation is incomplete or unexpected.

The Phase 1 WhatsApp UAT is not authorized by this implementation. It requires
Hans's explicit approval after review of the diff, tests, commit, push, and
runtime backup.
