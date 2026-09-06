---
name: team-tasking-artifact-delivery
description: "Deliver private pilot artifacts with safe encoding."
category: hve
version: 1.0
date: 2026-09-05
---

# team-tasking-artifact-delivery — Safe private artifact handling

Use this skill when a Phase 0 task includes a digital deliverable.

## Inline text artifacts

- Preserve the exact requested filename as a simple filename such as
  `checklist.md`; never include a path.
- Call `deliver_text_artifact` with the complete UTF-8 text in `content_text`.
  Do not Base64-encode inline text yourself.
- Keep the exact task ID from the approved card in `task_id`.
- Use a stable event ID so a retry cannot create a duplicate artifact.

`deliver_text_artifact` returns the filename, byte count, line count, SHA-256,
and final `awaiting_validation` state. Report those fields exactly.

## Binary artifacts

- Use `deliver_artifact` only when the payload is already binary or must remain
  binary-safe.
- Pass standard Base64 only in `content_base64`; never pass Markdown, JSON,
  shell syntax, or a data URL in that field.
- If Base64 encoding cannot be performed reliably, stop and ask for a retry or
  use an available local encoding tool. Do not guess, truncate, or substitute
  raw text.

## Stored artifacts

The pilot artifact directory is private and local. Do not use `read_file` to
inspect a stored artifact unless the file is known to be text and the user
explicitly asks for its contents. The delivery response already provides the
path and SHA-256 hash. Treat binary-file warnings as a handling issue, not as
evidence that delivery failed.

After a confirmed delivery, report only the returned filename, byte count, line
count, SHA-256, and `awaiting_validation` state, then stop. Do not call
`report_done`, `validate_task`, `terminal`, browser/web, or unrelated tools in
the same turn.
