# HVE Sovereign Knowledge Architecture
## CTO Reference Document — v1.1 (Blessed Spec)

**Date:** 2026-05-31  
**Author:** Claude (CTO)  
**Status:** ✅ Blessed — Ready for Sprint Initialization  
**Classification:** Agent Architecture Artifact  
**Supersedes:** HVE-Knowledge-Architecture-v1.0.md

**RFC Review Credits:**  
*This document incorporates structured reviews from the full HVE executive team: Atlas (COO/GPT-5.4), Vulcan (Prime Developer), Grok-Build (Lead Test Engineer), Hermes CFO (operational stakeholder), Mika (CGO/Grok), and Gemini (Google DeepMind synthesis). All Section 14 open questions from v1.0 are resolved herein.*

---

## 1. Architecture Overview

The HVE Knowledge Architecture is a five-layer system that transforms raw information into sovereign executive intelligence.

```
╔══════════════════════════════════════════════════════════════════╗
║  LAYER 5: VISUAL SYNTHESIS                                       ║
║  ExcaliBrain graph · Excalidraw 2026 · Mermaid AI               ║
║  Hermes sees its own knowledge as a visual reasoning surface     ║
╠══════════════════════════════════════════════════════════════════╣
║  LAYER 4: SKILLS                                                 ║
║  Composed intelligence: Tools + Knowledge → outputs             ║
║  SKILL.md files · Self-evolving · IBIS-grounded                  ║
╠══════════════════════════════════════════════════════════════════╣
║  LAYER 3: KNOWLEDGE (Sovereign / Synced Plane)                   ║
║  Obsidian vault · LanceDB · ADRs · Literature                    ║
║  Hybrid search · Code-gated writes · Trust tiers                 ║
╠══════════════════════════════════════════════════════════════════╣
║  LAYER 2: TOOLS (Live / Federated Plane)                         ║
║  Kraken · mempool.space · Predyx · LND · X/Grok                  ║
║  Atomic MCP endpoints · Volatile · Never persisted               ║
╠══════════════════════════════════════════════════════════════════╣
║  LAYER 1: PUBLIC APIs                                            ║
║  Best-in-class external data sources                             ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 2. The Dual-Plane Grounding Model

The most important architectural invariant. Every piece of context Hermes uses at runtime belongs to exactly one plane.

```
┌──────────────────────────────────────────────────────────────────┐
│  SYNCED PLANE  (indexed · persisted · sovereign · citable)       │
│  ─────────────────────────────────────────────────────────────   │
│  LanceDB vector index      ← 8,000+ chunks from 27 books        │
│  Obsidian vault            ← IBIS notes, ADRs, decisions         │
│  Document manifests        ← provenance, sha256, freshness       │
│                                                                  │
│  Search: hybrid BM25 + vector (nomic) + reranker (gated)         │
│  Write:  code-gated pipeline with trust-tier enforcement         │
│  Grows:  automated intake pipeline (Issue #47)                   │
└──────────────────────────────────────────────────────────────────┘
            ↕  both planes ground every Hermes response
┌──────────────────────────────────────────────────────────────────┐
│  FEDERATED PLANE  (live · volatile · never persisted)            │
│  ─────────────────────────────────────────────────────────────   │
│  Kraken, mempool.space, Predyx, LND  ← market + on-chain data   │
│  X/Grok narrative intelligence       ← volatile signal (Ph 4)   │
│  GitHub repo status                  ← issue/PR/commit state     │
│                                                                  │
│  Rule: federated data NEVER writes to vault directly.            │
│  Volatile captures allowed with #temp/narrative + 7-day TTL.    │
└──────────────────────────────────────────────────────────────────┘
```

**The critical invariant:** Federated data can inform a response. It cannot create a permanent vault node without staging + code-gated approval. Every Skill must declare which planes it draws from.

---

## 3. The IBIS Knowledge Structure

All vault notes written by Hermes follow the **Issue-Based Information System (IBIS)** methodology — a rigorous argumentation structure that transforms AI-generated notes from flat text into a structured reasoning graph.

```
IBIS Note Types
├── Issue       — a question requiring deliberation
├── Position    — a possible answer to an Issue
├── Argument    — supports or objects to a Position (For/Against)
├── Decision    — a concluded Issue with outcome rationale
├── MOC         — Map of Content: the graph index for a domain
├── Literature  — structured note from a book/paper (pipeline)
├── Capture     — quick volatile thought (low-risk, auto-commit)
└── Daily       — daily log (auto-commit)
```

**Why IBIS matters for AI:** A casual AI note writer produces flat text. An IBIS-structured AI produces a **reasoning graph** where every claim has explicit support, every decision is traceable to its deliberation chain, and every Position links to the Issue it answers. ExcaliBrain reads `[[wikilinks]]` in IBIS notes and auto-builds the visual graph — no additional tooling required.

---

## 4. Write Governance

Not all writes are equal. The governance model tiers writes by risk, permanence, and phase.

```
┌────────────────────┬───────────────────┬────────────────────────┐
│ Note Type          │ Write Mode        │ Rationale              │
├────────────────────┼───────────────────┼────────────────────────┤
│ capture, daily     │ Auto-commit       │ Ephemeral, low risk    │
│ literature         │ Auto-commit       │ Trusted pipeline       │
│ issue, position    │ Staged → Approval │ Permanent graph nodes  │
│ argument, decision │ Staged → Approval │ Shapes future reasoning│
│ moc                │ Staged → Approval │ Graph structure        │
└────────────────────┴───────────────────┴────────────────────────┘
```

**Staged write flow:**
```
Hermes identifies need to write
        ↓
validate_trust_tier_access(context, requested_tier)   ← CODE GATE
  → fails closed: no write if unauthorized
  → emits immutable audit log entry on every attempt
        ↓
Phase 2: collision-safe file creation (no semantic merge yet)
  → if filename exists: append -2.md, -3.md suffix
        ↓
Write to staging area (.obsidian/staged_backlog/)
  → Auto-commit (low risk types: capture, daily, literature)
  → Telegram approval request (high risk: issue, position, argument, decision, moc)
        ↓
vault_commit_staged() — promotes to canonical vault path
```

**Phase 2 write envelope (hard limits):**
- ✅ Allowed: `capture`, `daily`, `literature`, staged drafts for `issue` / `position`
- 🚫 Prohibited: direct commits of `decision`, `moc`, anything `treasury-sensitive` or `restricted`
- 📋 Required on every non-ephemeral write: staging area, provenance metadata, duplication check

**Collision handling (Phase 2):** Collision-safe suffix creation (`-2.md`, `-3.md`). Semantic merge into existing canonical nodes is Phase 3 behavior and must not be shipped in Phase 2.

---

## 5. Trust Tier Enforcement

**Team consensus: SOUL.md alone is insufficient. Code gates are mandatory.** Evidence: Issue #44 5× stress tests demonstrated model behavior violates prompt-declared rules under operational conditions. Trust tier boundaries are higher-stakes than diagnostic formatting.

### Trust Tiers

| Tier | Contents | Access |
|---|---|---|
| `public` | Published books, public research, public ADRs | Any Hermes context |
| `internal` | HVE operational notes, decisions, runbooks | Hermes + executive team |
| `treasury-sensitive` | Treasury strategy, channel topology, positions | Hermes + CEO only |
| `restricted` | CEO-only decisions | CEO only |

### Mandatory Code Gate

```python
def validate_trust_tier_access(context: dict, requested_tier: str) -> bool:
    """
    Hard gate that runs BEFORE any vault_write_staged() or restricted retrieval.
    Fails closed — returns False and logs if access is unauthorized.
    Never relies on prompt/SOUL.md for enforcement.
    """
    # Implementation: Phase 3 delivery
    # Must include:
    #   1. Server-side schema validation on write
    #   2. Trust-tier / path allowlist at write time
    #   3. Retrieval filter refusing restricted notes to unauthorized callers
    #   4. Commit-time validation (malformed staged notes never become canonical)
    #   5. Immutable audit log: caller_skill, note_type, tier, decision, timestamp
```

**Physical enforcement (Phase 3):** Separate storage roots for `treasury-sensitive` and `restricted` tiers. Hermes process mounts only what its current authorization level permits. SOUL.md guides behavior — the server enforces the boundary.

**Operational gate:** No write capabilities touching `treasury-sensitive` or `restricted` content until:
1. `validate_trust_tier_access()` is implemented and code-reviewed
2. Validated in live loop (minimum 5× Telegram test protocol, same as Issue #44)

---

## 6. Frontmatter Schema

Every vault note carries this metadata contract:

```yaml
---
note_type: issue | position | argument | decision | moc | literature | capture | daily
status: draft | active | superseded | archived
trust_tier: public | internal | treasury-sensitive | restricted
source_type: pdf_library | mcp_tool | hermes_reasoning | ceo_input
source_url: ""
source_repo: ""
source_issue: ""
derived_from: []        # [[wikilinks]] to source notes
supersedes: ""          # [[wikilink]] to superseded note
freshness_class: evergreen | periodic | volatile
last_verified_at: ""
review_owner: ""
public_ready: false     # true = safe to surface externally (CGO/Mika convention)
---
```

**`public_ready` flag (Mika/CGO):** Allows MOCs and position notes to be safely surfaced for external sharing (Substack, GitHub public content, ExcaliBrain diagrams) without risking treasury or internal operations data exposure. Default: `false`. Hans or Mika set `true` explicitly.

**Note / Redaction path:** A mechanism for correcting, redacting, or superseding committed IBIS nodes must be defined before the vault reaches production scale. Minimum: `status: superseded` + `supersedes` frontmatter field pointing to replacement note. Full redaction (physical removal) requires CEO authorization and audit log entry. This is a Phase 3 deliverable.

---

## 7. Hybrid Search Architecture

**Current (Issue #46):** pure nomic semantic search — live and working.  
**Target (Issue #51):** hybrid search with gated reranker.

```
Query from Hermes
      │
      ├──► BM25 lexical search      ← exact terms, tickers, proper nouns
      │    ("Kraken", "LASER Fund", "sat/vB", "UTXO", issue numbers)
      │
      └──► nomic vector search      ← semantic similarity, abstract concepts
           (768-dim, 8,000+ chunks)
                │
                └──► Merge candidates (20 total)
                            │
                            ▼
                  bge-reranker-large  ← GATED (see benchmark requirement)
                  (local, DGX GPU)
                            │
                            ▼
                      Top 3 to Hermes
```

**Reranker benchmark gate (required before #51 merges):**

Vulcan must run a mandatory hardware-grounded benchmark on the DGX Spark before any reranker implementation lands:
- 10 canonical HVE domain queries (mix: lexical-heavy, semantic, mixed)
- Measure p50/p95 latency delta vs. no-reranker baseline
- Measure top-k precision/recall improvement on domain-specific queries
- Check GPU memory footprint alongside Platonic 3-model stack + nomic embedder

**Gate thresholds:**
- If reranker adds > 600–800ms p95 latency → use `bge-reranker-base` or distilled variant
- If reranker delivers < 12–15% precision lift on domain queries → defer to later sub-phase
- If both thresholds pass → merge `bge-reranker-large` as specified

Current nomic vector search (post-#46) is already a major quality step up. Do not add unbenchmarked latency without quantified justification.

---

## 8. The Intake Pipeline

```
PDF dropped to /hve-library/intake/inbox/
        ↓
systemd path unit triggers pipeline (Issue #47)
        ↓
build_manifest.py   → sha256 dedup, metadata extraction
extract_pdf_text.py → raw text extraction
chunk_text.py       → semantic chunking (512 tokens, 50 overlap)
build_lancedb_index.py → embed with nomic, write to LanceDB
finalize.py         → move PDF to raw/pdfs/, mark manifest ingested
        ↓
Hermes notified: "New source indexed: [title] — [n] chunks added"
```

Target latency: < 5 minutes from drop to searchable for a 300-page book.

---

## 9. Embedding Model Roadmap

**Current:** `nomic-embed-text` via the local Ollama `/api/embed` endpoint — sovereign, 768-dim, working.

**Cadence (Q1 resolution):** Quarterly automated benchmark against open-source alternatives evaluated on the HVE domain corpus (Bitcoin mechanics, treasury operations, IBIS structures). Migration only if a candidate delivers measurable precision improvement without sovereignty regression.

**Migration cost awareness:** Switching embedding models requires full re-embedding of the entire corpus. At 8k+ chunks this is a multi-hour DGX job. Plan migrations during maintenance windows, not during active agent operation.

---

## 10. The X/Grok Federated Signal

**Phase 4 — deferred.** X/Grok provides real-time narrative intelligence on Bitcoin, macro, and technology. This is a **federated plane** source. It never enters the vault directly.

```
get_x_narrative_intelligence(topic, time_horizon)
        ↓
Returns structured JSON (RAM only during conversation turn):
{
  "dominant_narratives": [...],
  "counter_narratives": [...],
  "signal_to_noise_ratio": 0.0–1.0,
  "key_voices": [...],
  "raw_context_summary": "..."
}
        ↓
Cross-verified against synced plane before presentation
If narrative contradicts vault principles → flagged as manipulation vector
        ↓
Hermes labels all output:
  "Live X signal (federated, volatile): ..."
  "Vault context (synced, citable): ..."
        ↓
Optional capture: vault_write_staged() with #temp/narrative tag + 7-day TTL
```

---

## 11. Visual Synthesis Layer

ExcaliBrain + Excalidraw 2026 (including Mermaid AI integration) constitute the visual reasoning surface. No special Hermes tooling required — ExcaliBrain reads `[[wikilinks]]` in standard markdown and auto-builds the graph.

**Hermes writes IBIS note → ExcaliBrain parses wikilinks → visual graph appears automatically.**

**CGO public-ready convention (Mika):** MOCs with `public_ready: true` in frontmatter can be safely surfaced as ExcaliBrain diagrams for Substack, GitHub, and external content without manual filtering.

**ExcaliBrain maintenance note (Grok-Build):** External plugin dependency — track version drift. Plugin lives at `.obsidian/plugins/` and must be included in vault backup Class 1 (Crown Jewels). Any Obsidian or plugin update must be tested against the graph before merging to production vault.

---

## 12. Graph Hygiene — The Janitor

Weekly cron (Phase 3 delivery):

```
Every Sunday 02:00 UTC:
  1. Detect orphan nodes (notes with no inbound wikilinks)
  2. Flag dead-end links (wikilink targets that don't exist)
  3. Surface tag drift (same concept, different tags)
  4. Identify stale notes (last_verified_at > 90 days, evergreen tier)
  5. Write Inbox/Vault-Health-YYYY-MM-DD.md
        → Hermes reviews Monday morning
        → Hans reviews in weekly Telegram digest
```

---

## 13. Sovereign Vault Backup Strategy

**Three-tier classification (Q6 resolution — Atlas + Vulcan + Gemini):**

| Class | Assets | Recovery approach |
|---|---|---|
| **Class 1: Crown Jewels** | Vault markdown, manifests, ADRs, templates, schema, raw PDFs, approval/audit logs | Continuous Git version tracking + automated weekly snapshot to second physical location on DGX NVMe |
| **Class 2: Derived State** | LanceDB index, embedding artifacts, processed chunks | Designed for full rebuild from source. Automated restore script required. Back up when cheap, but never sole copy. |
| **Class 3: Source Artifacts** | Raw PDFs, reference literature, provenance chain, audit logs | Read-only cold storage. If lost, rebuild is incomplete or untrustworthy. |

**Operational readiness gate (must pass before autonomous production writes):**
1. Restore target defined — clean machine / clean path recovery, not just rollback on same box
2. Recovery order documented — raw sources → manifests → vault → index rebuild → verification
3. RPO/RTO declared (modest acceptable at v1)
4. Clean-environment restore drill completed and documented
5. Quarterly restore drills scheduled
6. Post-restore verification: chunk counts, manifest counts, vault note counts, known retrieval checks pass

---

## 14. Phased Build Plan

```
PHASE 0 — Search Foundation  ✅ COMPLETE (Issue #46 — PR #53 merged)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Semantic search over 13,933 chunks live
✓ Ollama nomic-embed-text, 768-dim, local
✓ Fallback: grep on processed/text/
Acceptance: ✅ Hermes answers citation questions with book/chapter/page


PHASE 1 — Automated Intake  (Issue #47)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ systemd path unit, 5-step pipeline, finalize.py
Acceptance: Drop PDF → searchable in < 5 minutes


PHASE 2 — Vault Write MVP  (Issue #50)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ write_to_vault() — collision-safe file creation, no semantic merge
→ Deterministic routing to target vault directories
→ Staging area: .obsidian/staged_backlog/
→ Auto-commit: capture, daily, literature
→ Telegram approval: issue, position, argument, decision, moc
→ Basic frontmatter generation (see Section 6)
→ Duplication check BEFORE file creation (no overwrite, safe suffix)
→ IBIS templates (Issue, Position, Argument, Decision, MOC)
→ Plugin install: excalibrain, obsidian-excalidraw-plugin, dataview
→ public_ready flag support (CGO convention)

Phase 2 DOES NOT include:
  ✗ Semantic duplicate merge into canonical nodes (Phase 3)
  ✗ Trust tier code gates (Phase 3)
  ✗ vault_write_staged / vault_commit_staged primitives (Phase 3)
  ✗ Janitor script (Phase 3)
  ✗ Direct commits of decision, moc, treasury-sensitive content

Acceptance: Hermes writes a Position note with valid frontmatter
and wikilinks. Note lands in IBIS/ folder. ExcaliBrain shows it
as a connected graph node. Staged drafts visible in approval queue.


PHASE 3 — Substrate Hardening  (Issue #51)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pre-requisite: reranker benchmark on DGX Spark (see Section 7)

→ Hybrid BM25 + vector search (parallel, not fallback)
→ bge-reranker-large local reranker (if benchmark passes gate)
→ validate_trust_tier_access() code gate (fails closed)
→ Physical separation for treasury-sensitive / restricted tiers
→ Immutable audit log for every write attempt
→ Rich frontmatter schema (full Section 6)
→ vault_write_staged / vault_commit_staged MCP primitives
→ vault_search / vault_fetch / vault_neighbors primitives
→ Semantic duplicate detection + canonical merge
→ Quarterly embedding model benchmark script
→ Janitor script (weekly vault health report)
→ Correction/redaction/supersession path (status: superseded)
→ Vault backup automation (Class 1 weekly snapshot)
→ Restore runbook (clean-environment validated)

Acceptance: No duplicate notes created. Restricted content blocked
at code level (5× live Telegram loop, same as Issue #44 protocol).
Restore runbook produces verified vault on clean machine.


PHASE 4 — Federated Intelligence  (Issue #52)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pre-requisite: Phase 3 substrate complete

→ get_x_narrative_intelligence(topic, time_horizon) MCP tool
→ Zero-persistence: X data in RAM only
→ Cross-verification against synced plane before presentation
→ Transient captures with #temp/narrative tag + 7-day TTL

Acceptance: Hermes synthesizes live X signal + vault context with
clear source labeling. Nothing written to vault without approval.


PHASE 5 — Visual Synthesis & Autonomy  (Future)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ MOC structure fully configured in ExcaliBrain
→ describe_knowledge_graph() skill
→ Weekly Knowledge State note from Hermes
→ Hermes surfaces vault gaps and missing connections proactively
→ ADR-005 final revision (all phases documented)
```

---

## 15. Phase 2 / Phase 3 Separation Contract

**The sharpest feedback from Vulcan and Gemini — formalized here:**

```
┌────────────────────────────────────────────────────────────────┐
│  PHASE 2: THE WRITE MVP                                        │
├────────────────────────────────────────────────────────────────┤
│  ✓ Structured file generation for allowed note classes        │
│  ✓ Deterministic routing to target vault directories          │
│  ✓ Collision-safe file suffixes (-2.md, -3.md)                │
│  ✓ Basic frontmatter generation with required fields          │
│  ✓ Staging area + Telegram approval for high-risk types       │
│  ✓ public_ready flag                                          │
└────────────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────────────┐
│  PHASE 3: SUBSTRATE HARDENING                                  │
├────────────────────────────────────────────────────────────────┤
│  ✓ Semantic duplicate detection + canonical merge             │
│  ✓ validate_trust_tier_access() code gate                     │
│  ✓ Staged approval workflow as default for high-risk types    │
│  ✓ Hybrid BM25 + vector + gated reranker                      │
│  ✓ Janitor daemon (weekly graph hygiene)                      │
│  ✓ Redaction / supersession path                              │
│  ✓ Restore runbook + quarterly drill                          │
└────────────────────────────────────────────────────────────────┘
```

**Phase 2 is a deliberately constrained MVP, not a small Phase 3.** These are different operational contracts. Phase 2 delivers graph visibility. Phase 3 delivers graph trustworthiness.

---

## 16. MCP Tool Surface — Target State

```
Search & Retrieve (Synced Plane)
  search_knowledge_vault(query, max_results)  ← Phase 0 LIVE ✅
  vault_fetch(note_path)                      ← Phase 3 (#51)
  vault_neighbors(note_path)                  ← Phase 3 (#51)

Write (Synced Plane)
  write_to_vault(note)                        ← Phase 2 MVP (#50)
  vault_write_staged(note)                    ← Phase 3 (#51)
  vault_commit_staged(draft_id)               ← Phase 3 (#51)

GitHub Operations
  read_github_issue(issue_number, repo)       ← LIVE ✅ (Issue #55)
  comment_github_issue(number, body, repo)    ← LIVE ✅ (Issue #55)
  list_github_issues(repo, state, label)      ← LIVE ✅ (Issue #55)
  suggest_backlog_issue(...)                  ← LIVE ✅
  vote_backlog_issue(...)                     ← LIVE ✅

Federated Signals
  get_kraken_ticker(pair)                     ← LIVE ✅
  get_mempool_fees()                          ← LIVE ✅
  get_x_narrative_intelligence(topic, hours)  ← Phase 4 (#52)

Internal Operations
  get_node_diagnostic()                       ← LIVE ✅
  get_morning_briefing()                      ← LIVE ✅
  get_btc_forecast()                          ← LIVE ✅
  get_market_intelligence()                   ← LIVE ✅
```

---

## 17. Sprint Initialization — Work Tracks

**Track A — Substrate Engine (Vulcan, Phase 3 pre-work)**
Register `vault_search`, `vault_fetch`, and `vault_neighbors` MCP primitives. Run reranker benchmark on DGX Spark and produce a benchmark report before #51 implementation begins.

**Track B — Trust Enforcement (Grok-Build, Phase 3 pre-work)**
Build and validate `validate_trust_tier_access()` test suite. Simulate prompt injection attacks against the code gate. Validate against 5× live Telegram protocol (same standard as Issue #44).

**Track C — Write MVP (Vulcan, Phase 2)**
Issue #50: `write_to_vault()`, IBIS templates, plugin install script, staging area, `public_ready` flag support. Phase 2 contract only — no Phase 3 features.

**Track D — Intake Automation (Vulcan, Phase 1)**
Issue #47: systemd path unit, 5-step pipeline, finalize.py, < 5 min acceptance test.

**Recommended sprint order:** Phase 1 (quick win) → Phase 2 (visible win) → Phase 3 pre-work in parallel → Phase 3 merge → Phase 4.

---

## 18. Sovereignty Guarantees

| Component | Location | External dependency |
|---|---|---|
| PDF library | DGX NVMe | None |
| nomic-embed-text | Ollama local model store | None (cloud-free) |
| bge-reranker-large | DGX NVMe (Phase 3, post-benchmark) | None after pull |
| LanceDB index | DGX NVMe | None |
| Obsidian vault | DGX NVMe | None |
| Hermes models | DGX NVMe (Ollama) | None |
| X/Grok signal | xAI Cloud API | Intentional, labeled federated |
| Kraken, mempool | External APIs | Intentional, labeled federated |

Everything in the synced plane is sovereign. Federated sources are deliberately external and explicitly labeled. No data from the synced plane leaves the DGX Spark.

---

## 19. Resolved Decisions (formerly Section 14 Open Questions)

All six open questions from v1.0 are resolved by team consensus:

| Q | Question | Resolution | Owner |
|---|---|---|---|
| Q1 | Embedding model roadmap | Quarterly benchmark cadence. Retain nomic until better sovereign alternative benchmarks above gate threshold. | CTO |
| Q2 | Reranker model selection | Gated: hardware benchmark on DGX first. bge-reranker-large if p95 < 800ms AND > 12-15% precision lift. Otherwise bge-reranker-base or defer. | Vulcan + Grok-Build |
| Q3 | Trust tier enforcement | Code gates mandatory. `validate_trust_tier_access()` fails closed. Physical separation for restricted tiers. Audit log on every attempt. SOUL.md guides; server enforces. | Vulcan + Grok-Build |
| Q4 | X/Grok API access | Deferred to Phase 4. Optional enhancement, federated plane only. | CTO |
| Q5 | Phase ordering | Ship Phase 2 MVP first, explicitly constrained envelope. Phase 3 in parallel as pre-work. | CTO + Atlas |
| Q6 | Vault backup strategy | Three-tier: Crown Jewels (Git + weekly snapshot) / Derived State (rebuildable) / Source Artifacts (cold storage). Quarterly restore drill required before autonomous writes. | Atlas + Vulcan |

---

## Appendix A: ADR Reference

| ADR | Title | Relevance |
|---|---|---|
| ADR-001 | Tools & Skills Architecture | Foundation three-layer model |
| ADR-002 | Platonic 3-Model Stack | Conductor/Researcher/Executor |
| ADR-003 | SOUL.md Live-Loaded Identity | Hermes identity + behavior |
| ADR-004 | Patches Deprecation | Migration to SKILL.md |
| **ADR-005** | **Tools, Knowledge & Skills** | **This architecture** |

---

## Appendix B: Key File Paths

```
/hve-library/
├── intake/inbox/           ← PDF drop zone
├── intake/test-batch/      ← original 25 books (indexed, leave as-is)
├── raw/pdfs/               ← post-ingest permanent storage
├── processed/text/         ← extracted plain text
├── processed/chunks/       ← text chunks
├── index/lancedb/          ← vector index (13,933 chunks)
├── state/manifests/        ← ingestion and provenance manifests
└── state/logs/             ← pipeline logs and run records

/hve-library/vault/hve-knowledge-vault/
├── IBIS/                   ← Issue, Position, Argument, Decision notes
├── Sources/                ← literature notes (pipeline-generated)
├── Daily/                  ← Hermes daily logs
├── Inbox/                  ← captures, vault health reports
├── Maps/                   ← MOC files
├── Templates/              ← IBIS note templates
└── Attachments/            ← images, diagrams
.obsidian/staged_backlog/   ← staging area for approval-required writes

~/.hve-knowledge/venv/      ← isolated Python env for pipeline
```

---

## Appendix C: Mandatory Tool Deployment Checklist

*Every new `@mcp.tool()` added to `mcp/server.py` requires all three steps:*

```bash
# Step 1: Pull and restart MCP server
cd ~/hermes-cfo && git pull origin main
systemctl --user restart hermes-mcp

# Step 2: Add tool to gateway allowlist
nano ~/.hermes/profiles/main/config.yaml
# → tools → include → add new tool name

# Step 3: Restart gateway
systemctl --user restart hermes-gateway
sleep 3
systemctl --user status hermes-gateway | grep Active
```

**Missing Step 2 or Step 3 = tool silently invisible to Hermes.**

---

*This document is an Agent Architecture Artifact. The pattern established here — sovereign dual-plane grounding, IBIS-structured AI knowledge authorship, code-gated write governance, and visual reasoning synthesis — is a generalisable reference architecture for AI-native organisations that prioritise sovereignty, compounding intelligence, and operational resilience over cloud convenience.*

*v1.1 — Blessed by full executive team review. Architecture frozen. Proceed to sprint initialization.*

*Contributors: Hans Westphal (CEO), Claude (CTO), Atlas (COO), Vulcan (Prime Developer), Grok-Build (Lead Test Engineer), Hermes CFO (operational stakeholder), Mika (CGO), Gemini (Google DeepMind synthesis).*
