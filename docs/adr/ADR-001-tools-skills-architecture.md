# ADR-001: Hermes Capability Architecture — Tools, Skills, and Self-Evolution

**Date:** 2026-05-30  
**Status:** Accepted  
**Authors:** Hans Westphal (CEO), Claude (CTO)  
**Classification:** Agent Architecture Artifact

---

## Context

As we build out Hermes (HVE's AI CFO), we needed a principled answer to: *how does the agent's capability set grow over time without requiring constant engineering intervention?*

The pattern emerged organically during development of Issues #18, #22, and #31. This ADR formalises it.

---

## Decision

Hermes capabilities are organised in three layers:

```
Layer 1: PUBLIC APIs
   Best-in-class external data sources
   (Polymarket, Kalshi, Kraken, on-chain data, news feeds...)
         ↓
Layer 2: TOOLS  (atomic MCP endpoints)
   Each API wrapped as a single @mcp.tool() function
   One operation, one source, deterministic output
   Built by Vulcan, reviewed by Claude, validated by Grok
         ↓
Layer 3: SKILLS  (composed workflows)
   LLM-composed chains of tools → complete intelligence outputs
   Hermes self-evolves these from the available toolset
   No new code required — new skills emerge from tool combinations
```

---

## The Self-Evolution Insight

**Tools are code. Skills are intelligence.**

Once the toolset is rich enough, Hermes can compose new skills autonomously — identifying combinations of existing tools that produce valuable outputs. A new "skill" is simply a documented pattern of tool calls that Hermes repeats reliably.

Example:
- `get_btc_price` + `get_market_intelligence` + `get_node_diagnostic`  
  → **Skill: Daily Treasury Pulse** — no new code, just Hermes learning to chain them

This means the capability ceiling is set by the *toolset*, not by engineering throughput. Every new API we wrap multiplies Hermes's potential skill surface.

---

## Principles

### 1. APIs first — wrap everything useful
Identify the best public APIs relevant to our mission:
- Financial data (Kraken, Polymarket, Kalshi, on-chain explorers)
- Intelligence (news feeds, social sentiment)
- Infrastructure (LND, BTCPay, node metrics)
- Business (calendar, task management, client data)

Each becomes a Tool. The combination becomes Hermes's world-model.

### 2. Tools are atomic and deterministic
A Tool must:
- Do exactly one thing
- Return structured data (JSON)
- Complete in < 5s where practical, or fail explicitly
- Never fail silently
- Require no LLM reasoning internally

### 3. Skills are composable and emergent
A Skill is a documented, repeatable pattern of tool calls:
- Defined as a `SKILL.md` document in `skills/`
- Can be created by Hermes when it discovers a useful combination
- Graduated to `skills/` directory when used 3+ times reliably
- Reviewed by CTO before being treated as production

### 4. SOUL.md stays lean; skills own playbooks
SOUL.md remains the always-loaded identity and guardrail document:
- Identity, mission, architecture, and hard constraints
- Mandatory tool-enforcement guardrails that must remain in-context every turn

`skills/` owns the playbooks:
- When to invoke a domain workflow
- Which tool or terminal command to call for that workflow
- Output and fallback rules for that workflow

---

## File Structure (current target state)

```
humanvalueexchange/hanshermesagent/
├── mcp/
│   ├── server.py                    # FastMCP server — registers atomic tools
│   └── tools/
│       └── knowledge/search.py      # LanceDB semantic search script via knowledge venv
├── tools/                           # Shared Python helpers used by MCP server
│   ├── mempool/
│   │   ├── client.py                # urllib client — mempool.space
│   │   └── tools.py                 # get_mempool_fees, get_mempool_depth, get_block_status, get_lightning_network_stats
│   └── knowledge.py                 # semantic search orchestration + grep fallback
├── skills/
│   └── hve/
│       ├── bitcoin-intelligence/SKILL.md
│       ├── node-health/SKILL.md
│       ├── treasury-operations/SKILL.md
│       ├── knowledge-management/SKILL.md
│       └── backlog-management/SKILL.md
├── dotfiles/
│   └── SOUL.md                      # Lean identity + always-on guardrails
├── docs/
│   ├── dev-loop-protocol.md
│   └── adr/
│       └── ADR-001-tools-skills-architecture.md
└── scripts/
    └── validate-hermes-mcp.sh       # MCP health and wiring validator
```

**Import-path constraint:** `mcp/server.py` must preserve a stable import path for both installed `mcp` packages and repo-local helper modules. Shared helpers therefore live in top-level `tools/`, and standalone subprocess entrypoints live under `mcp/tools/` when they must run in isolated environments.

---

## API Wishlist (seed list — grow over time)

| Category | API | Use Case | Status |
|---|---|---|---|
| BTC Price | Kraken REST | Live price for all calculations | ✅ Live |
| Prediction Markets | Polymarket gamma-api | BTC event probabilities | Issue #31 |
| Prediction Markets | Predyx | Lightning-native odds (API pending) | Issue #31 |
| On-chain | mempool.space | Fee rates, block data, UTXO analysis | ✅ Live (Issue #42) |
| Knowledge | LanceDB + nomic embeddings | Semantic library search | ✅ Live (Issue #46) |
| Node | LND REST | Channel balances, routing, invoices | Mercury |
| News | RSS/NewsAPI | BTC narrative signals | Issue #22 |
| Macro | FRED API | Interest rates, M2, macro context | Backlog |
| Calendar | iCal/Google | Scheduling context for decisions | Backlog |

---

## Consequences

**Positive:**
- Hermes capability grows without linear engineering effort
- Each new API multiplies potential skill combinations
- Skills can be human-approved before becoming operational
- Clear separation: engineers build tools, Hermes builds skills

**Risks to manage:**
- LLM orchestration errors increase with tool count — mitigated by skills/ layer as the tool surface grows
- Tool quality gates must be strict — bad tools corrupt all downstream skills
- Self-evolved skills need human review before production use

---

## Relation to Other Decisions

- SOUL.md tool-enforcement model — the guardrail mechanism for this pattern
- Issue #18 dependency tree (#15, #16, #17) — each is a skill built on the market_intelligence tool
- Mercury self-improvement loop — analogous pattern at the Bitcoin/payments layer

---

*This is an Agent Architecture Artifact. The pattern of self-evolving skills from a curated toolset is a generalisable design principle for AI-native organisations.*

---

## CTO Note — 2026-05-30: Independent Convergence with Microsoft Copilot

*Posted by Claude (CTO) following a CEO architecture discussion.*

After publishing ADR-001, we noticed that **Microsoft 365 Copilot Studio** uses an identical two-layer capability model:

| Microsoft Copilot | Hermes / ADR-001 |
|---|---|
| **Plugin** | **Tool** (`@mcp.tool()`) |
| **Skill** | **Skill** (`skills/hve/*/SKILL.md`) |
| Plugin registry (manifest) | Always-on tool guardrails in SOUL.md + explicit `SKILL.md` playbooks |
| Skills chain plugins | Skills chain tools |

The architectural mapping is exact. A Plugin in Copilot is an atomic connector to an external API. A Skill is a goal-oriented capability that the agent composes from plugins.

**What makes this significant:** Microsoft arrived at this pattern from the top down — a $3T enterprise product organisation with hundreds of engineers. We arrived at it from the bottom up — one CEO, one AI CTO, building a sovereign AI CFO on a single DGX Spark.

**Same architecture. Different origin. No coordination.**

This is not a coincidence. It suggests this two-layer pattern (atomic connectors → composed capabilities) is a *fundamental law of agentic systems* — the same way REST emerged as the natural API pattern, or double-entry bookkeeping emerged as the natural accounting pattern. The architecture is correct because the problem space demands it.

> *"Engineers build tools. Agents build skills."*
> — converged conclusion, HVE and Microsoft, independently, 2025–2026

The implication for HVE: every MCP tool we ship is not just a feature — it is **surface area for Hermes to self-evolve**. The engineering investment compounds. This is the sovereign AI flywheel.

---

## Amendment — Issue #44: SOUL.md → SKILL.md Decomposition (2026-05-30)

*Posted by Claude (CTO) after recognising SOUL.md bloat as a systemic problem.*

### What changed

SOUL.md grew across Issues #2–#42, accumulating numbered rules and a full tool registry table. Each new MCP tool required a new row and another rule section. At this growth rate, SOUL.md would become unmanageable and degrade reasoning quality by consuming context that should be available for actual CFO work.

**Root cause:** We were using SOUL.md as both an identity document and a tool invocation manual. ADR-001 Principle #4 always called for skills separation — we just had not implemented it yet.

### The refined principle

| Before | After |
|---|---|
| SOUL.md = identity + skill registry | SOUL.md = identity + always-on guardrails |
| Tool invocation rules in numbered Rule sections | Tool invocation rules in `SKILL.md` files |
| Each new tool bloats SOUL.md | Each new tool updates a domain skill or adds a new skill |
| Context consumed by invocation logic | Context available for CFO reasoning |

### Skill file format

Skills are native Hermes `SKILL.md` files — YAML frontmatter + markdown instructions. Loaded by Hermes at startup from `skills/hve/` via `config.yaml: skills.external_dirs`.

### Five HVE domain skills

| Skill | Domain tools |
|---|---|
| `bitcoin-intelligence` | BTC spot command + 4x mempool tools |
| `node-health` | `get_node_diagnostic` |
| `treasury-operations` | `get_morning_briefing`, `get_btc_forecast`, `get_market_intelligence` |
| `knowledge-management` | `search_knowledge_vault`, `create_task`, `get_client_context`, `get_capability_assessment` |
| `backlog-management` | `suggest_backlog_issue`, `vote_backlog_issue` |

### Why this matters architecturally

This amendment completes the original ADR-001 intent. Skills are now truly first-class citizens — not embedded footnotes in a system prompt. Each domain skill is versioned, independently maintainable, and composable.

*"Identity is sovereign. Tools are capability. Skills are intelligence."*  
*— HVE architecture evolution, Issue #44, 2026-05-30*
