---
name: team-tasking-mcp-discipline
description: "Use named pilot MCP tools with complete task arguments."
category: hve
version: 1.0
date: 2026-09-05
---

# team-tasking-mcp-discipline — Exact pilot tool calls

Use this skill whenever the Hans-only Phase 0 tasking pilot is active.

## Required procedure

1. Select the named `hve-team-tasking-pilot` MCP tool directly.
2. Copy the exact `task_id` returned by `normalize_task`; never reconstruct it,
   shorten it, or replace it with a title.
3. Supply every required argument from the tool schema before calling it.
4. Use a unique, stable `event_id` for each lifecycle message. Reusing the
   same event ID is safe only when intentionally retrying the same operation.
5. Treat the structured response as authoritative. Only report success when
   `confirmed` is true.

Never call a generic `tool_call` wrapper, call a tool without its name, omit
`task_id`, or invent an argument name. If a required value is missing, ask Hans
for it instead of guessing.

Read-only tools (`task_status_digest` and `task_audit_trail`) report state; they
do not replace `starting`, `blocked`, `retry`, `deliver_artifact`,
`report_done`, or `validate_task`.

For inline UTF-8 artifacts, use `deliver_text_artifact`; reserve
`deliver_artifact` for binary-safe Base64 payloads. After either delivery tool
confirms `awaiting_validation`, report the returned metadata and stop without
calling any other tool in that turn.
