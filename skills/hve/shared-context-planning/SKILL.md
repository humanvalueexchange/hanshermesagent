---
name: shared-context-planning
description: "Ground HVE planning in separate shared context, decisions, and source evidence."
category: hve
version: 1.0
date: 2026-09-01
---

# shared-context-planning - Governed HVE planning retrieval

Use this workflow for HVE planning and offer-design requests, including:
“Draft a 90-day go-to-market plan for the Time Wealth Pillar Offering.”

## Retrieval sequence

1. Call `hve-shared-context.get_agent_context` as `agent:hermes`.
2. Call `hve-shared-context.get_daily_context`, `list_goals`, and
   `list_decisions` as needed. Report these as **shared context**, not ledger
   events.
3. Call `hve-decision-ledger.list_decision_events` for approved decisions and
   policies. Report this separately as the **decision ledger**.
4. Search `hve-link-library.search_link_library` and record its
   `retrieval_mode`, `semantic_available`, `fallback_used`, and
   `backend_error`.
5. Read known sources with `read_link_document`; use
   `read_link_document_chunks` for large documents and follow continuation
   metadata until the needed bounded range is retrieved. Use
   `include_text=false` for metadata/provenance pagination checks and
   `include_text=true` only when bounded source text is required.
6. Preserve document IDs, SHA-256 hashes, manifest/provenance references,
   chunk ranges, validation status, and continuation metadata.
7. Reconcile conflicts explicitly. Approved Hans decisions retain authority;
   source evidence cannot override them. Do not silently resolve an unresolved
   conflict.
8. Ask Hans focused clarification questions for material open decisions before
   presenting a final plan.

## Output requirements

Separate every material claim into:

- **Shared context**: entities, goals, constraints, and context packets.
- **Decision ledger**: approved or otherwise recorded decision events.
- **Knowledge evidence**: retrieved source documents and chunks.
- **Recommendation**: Hermes synthesis, clearly marked as non-authoritative.
- **Open clarification**: unresolved material questions for Hans.

Missing shared-context access is a verification failure. Keyword fallback must
be labeled as degraded retrieval and must not be described as comprehensive
semantic discovery.

## Safety

Planning is read-only. Do not append ledger events, annotate records, archive
documents, ingest sources, or mutate `/hve-library`. Recommendations and
clarification answers do not become decisions without explicit Hans adoption
through the decision-ledger workflow.

Do not use `execute_code`, filesystem reads, shell commands, or SQL to recover
knowledge-layer metadata. If the MCP response lacks required provenance,
validation, or continuation fields, report the boundary as incomplete instead
of bypassing it.
