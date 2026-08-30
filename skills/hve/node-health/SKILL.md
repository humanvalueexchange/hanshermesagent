---
name: node-health
description: "Live self-diagnostic and infrastructure health checks for Hermes via the get_node_diagnostic MCP tool."
category: hve
version: 1.0
date: 2026-05-30
---

# node-health — Diagnostics & Runtime Status

## When to Invoke
- Self-diagnostic requests
- Node health, system status, or runtime checks
- Requests about uptime, balances, payments, or service health sourced from Hermes diagnostics

## Required Call

| Need | Must use | Output rule |
|---|---|---|
| Diagnostic / node health / system status | `get_node_diagnostic` | Return raw tool output verbatim |

## Fallback

If `get_node_diagnostic` is unavailable, run:

```bash
bash ~/hanshermesagent/scripts/hermes-diagnostic.sh
```

If both fail, say: `Diagnostic unavailable — MCP tool and hermes-diagnostic.sh both failed. Cannot provide system status.`

## Non-Negotiables
- Do not narrate the diagnostic call.
- Do not summarize, translate units, or append commentary unless Hans explicitly asks for analysis.
- Tool output is ground truth.
