# ADR-002: Platonic 3-Model Stack — Conductor / Clarifier / Executor

**Date:** 2026-05-30  
**Status:** Superseded by the current local four-model stack documented in
`README.md`, `VERSION.md`, and `dotfiles/SOUL.md`. Retained as historical
architecture context.  
**Authors:** Hans Westphal (CEO), Claude (CTO)  
**Classification:** Agent Architecture Artifact

---

## Context

Hermes CFO began life as a **4-agent stack**: Conductor (`qwen2.5:14b`) + Research (`mistral-small:24b`) + Execution (`nemotron-3-nano:30b`) + Critic (`gemma2:27b`). Three significant problems emerged in production:

1. **Context window failure** — `gemma2:27b` has an 8K context window. Fixed system prompt overhead (SOUL.md ~2,500 tokens + MCP tool definitions ~800 tokens + market data hook ~300 tokens) consumed ~4,000 of the available 8K, leaving under 4K for actual conversation. CFO sessions crash mid-flow.

2. **Hallucination under timeout** — the Critic approval loop added latency; under Telegram timeouts, the Conductor skipped tool calls and fabricated results rather than wait (hallucination root cause, 2026-05-20 incident).

3. **Memory pressure** — 4 models loaded simultaneously consumed >112 GB of 121 GB available unified memory, pushing 6.4 GB into swap and degrading first-token latency.

---

## Decision

Collapse to a **Platonic 3-model stack** with inline veto:

| Role | Model | Context | RAM | Function |
|---|---|---|---|---|
| Conductor | `qwen3.5:9b` | 262K | 6.6 GB | Orchestrate, synthesize, risk-gate (inline CONDUCTOR:APPROVE / CONDUCTOR:VETO) |
| Clarifier | `mistral-small:24b` | 131K | 14 GB | Market analysis, research, strategy briefing |
| Executor | `nemotron-3-nano:30b` | 131K | 24 GB | Position math, tool execution, audit trail |

**Total: ~45 GB / 128 GB** — 83 GB headroom for model growth and concurrent workloads.

The separate Critic model is eliminated. The Conductor performs inline veto using the `CONDUCTOR:APPROVE` / `CONDUCTOR:VETO` token pair. This removes the approval-loop timeout vulnerability and the context window failure mode simultaneously.

`gemma2:27b` remains installed on the DGX for Open WebUI debug sessions only — it is explicitly excluded from the Telegram production stack.

---

## Model Swap History

| Date | From | To | Rationale |
|---|---|---|---|
| 2026-05-30 | `gemma2:27b` (Critic) | Eliminated | 8K context too small for live CFO sessions |
| 2026-05-30 | `qwen2.5:14b` (Conductor) | `qwen3.5:27b` | 262K context, modern architecture |
| 2026-05-30 | `qwen3.5:27b` (Conductor) | `qwen3.5:9b` | 27b over-provisioned; 9b identical quality at 6.6 GB vs 17 GB |

---

## Consequences

- **Positive:** Eliminates approval-loop timeout hallucination; frees ~83 GB headroom; improves first-token latency (Issue #26)
- **Positive:** Simpler flow — 3 agents, 1 decision gate (CONDUCTOR:APPROVE), easier to debug
- **Trade-off:** Inline veto is less independent than a dedicated Critic — Conductor judges its own decisions
- **Mitigated by:** Hard constraints in SOUL.md (non-negotiable position limits, circuit breakers) that the Conductor cannot override

---

## Related

- Issue #26 (Hermes responsiveness / performance)  
- `dotfiles/SOUL.md` — Decision Flow section  
- `skills/trading/hermes-critic/SKILL.md` — Critic deprecation notice
