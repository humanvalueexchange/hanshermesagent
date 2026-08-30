# ADR-005: Hermes Capability Architecture — Tools, Knowledge, and Skills

**Date:** 2026-05-31  
**Status:** Accepted  
**Authors:** Hans Westphal (CEO), Claude (CTO)  
**Classification:** Agent Architecture Artifact  
**Supersedes:** ADR-001 (extends, does not replace)

---

## Context

ADR-001 established a three-layer capability model: Public APIs → Tools → Skills.

During Issue #46 (wiring `search_knowledge_vault` to LanceDB), we identified that this model was incomplete. Hermes has a fourth input that sits between Tools and Skills: **ingested knowledge from the PDF library**.

A Skill composed from Tools alone can answer *what is happening now*. A Skill composed from Tools **and** Knowledge can answer *what is happening now, in the context of what we know* — producing the kind of synthesis that defines genuine CFO intelligence.

---

## Decision

Hermes capabilities are organised in four layers:

```
Layer 1: PUBLIC APIs
   Best-in-class external data sources
   (Kraken, Polymarket, mempool.space, LND, news feeds...)
         ↓
Layer 2: TOOLS  (atomic MCP endpoints)
   Each API wrapped as a single @mcp.tool() function
   One operation, one source, deterministic output
   Built by Vulcan, reviewed by CTO, validated by Grok
         ↓
Layer 3: KNOWLEDGE  (ingested library)
   PDF library → extract → chunk → embed → LanceDB
   Queried via search_knowledge_vault MCP tool
   Source of durable context: books, papers, strategy docs
         ↓
Layer 4: SKILLS  (composed workflows)
   Hermes chains Tools + Knowledge → complete intelligence outputs
   SKILL.md files define when and how to combine both
   Self-evolves as toolset and library grow
```

---

## The Knowledge Layer Insight

**Tools answer: what is happening now.**  
**Knowledge answers: what do we know.**  
**Skills synthesise both.**

A Skill without Knowledge is reactive — it can report current fee rates or BTC price. A Skill with Knowledge is strategic — it can contextualize current market conditions against risk frameworks from the library, apply tax-efficiency principles Hans has studied, or surface relevant historical patterns when evaluating a position.

Example:
- `get_mempool_fees` → current fee rate is 45 sat/vB
- `search_knowledge_vault("on-chain batching efficiency")` → retrieved context from library
- **Skill: Channel Open Timing** — combines live fee data with ingested best practices

This is the difference between a dashboard and an advisor.

---

## The PDF Ingest Pipeline (already built)

```
/hve-library/intake/inbox/     ← drop zone for new PDFs
         ↓  (hve-library-manifest.timer)
/hve-library/state/manifests/  ← document metadata JSON
         ↓  (hve-pdf-extract.timer)
/hve-library/processed/text/   ← extracted plain text
         ↓  (hve-library-chunk.timer)
/hve-library/processed/chunks/ ← text chunks
         ↓  (hve-library-index.timer)
/hve-library/index/lancedb/    ← vector index (Ollama nomic-embed-text, 768-dim)
         ↓
search_knowledge_vault MCP tool ← Hermes queries here
```

**Current state (2026-05-31):** 25 PDFs, 7,454 chunks indexed.  
**Embedding model:** `nomic-embed-text` via the local Ollama `/api/embed` endpoint.  
**Ingest runtime:** `~/.hve-knowledge/venv/` — isolated from MCP server

---

## The Dual-Plane Model

*Added 2026-05-31 following team architecture review (Grok, Gemini/Google DeepMind, Atlas/Microsoft, CTO).*

The four-layer capability model above describes **what** Hermes knows. The dual-plane model describes **how** Hermes grounds its responses at runtime.

```
┌─────────────────────────────────────────────────────────┐
│  SYNCED PLANE (indexed, persisted, sovereign)           │
│  ─────────────────────────────────────────────────────  │
│  LanceDB vector index    ← PDF library (27+ books)      │
│  Obsidian vault          ← IBIS notes, ADRs, runbooks   │
│  Manifests / state       ← provenance + freshness       │
│                                                         │
│  Retrieval: hybrid BM25 + vector + local reranker       │
│  Write:     staged pipeline with trust-tier governance  │
└─────────────────────────────────────────────────────────┘
            ↕  Hermes grounds responses against both planes
┌─────────────────────────────────────────────────────────┐
│  FEDERATED PLANE (live at runtime, never persisted)     │
│  ─────────────────────────────────────────────────────  │
│  Kraken, mempool.space, Predyx, LND  ← live MCP tools  │
│  X/Grok narrative intelligence       ← volatile signal  │
│  GitHub repo status                  ← issue/PR state   │
│                                                         │
│  Rule: federated data NEVER writes to vault directly.   │
│  It can inform a response or be staged for approval.    │
└─────────────────────────────────────────────────────────┘
```

**The critical invariant:** Hermes always knows which plane a piece of context came from. A fact from the synced plane carries provenance and can be cited. A fact from the federated plane is volatile and must be labeled as such.

This is the grounding architecture for all future Hermes intelligence. Every Skill must declare which planes it draws from.

---

## Principles

### 1. Knowledge is a first-class capability layer
The PDF library is not a filing system — it is the substrate from which Hermes builds strategic intelligence. Every book Hans ingests expands Hermes's reasoning surface.

### 2. Tools are live. Knowledge is durable.
Tools expire (a fee rate from 10 minutes ago is stale). Knowledge compounds (a risk framework from a book read last year is still valid). Skills must know which input type they are drawing from and treat them accordingly.

### 3. The ingest pipeline is sovereign
PDFs land locally. Embeddings are computed locally. The index lives on NVMe. No external embedding APIs. No data leaves the DGX Spark.

### 4. search_knowledge_vault is the knowledge interface
All knowledge retrieval flows through one MCP tool. The tool abstracts the vector index — Hermes does not need to know about LanceDB, embeddings, or chunking. It asks a question; the tool returns relevant excerpts with provenance (book, author, chapter, page).

*Phase 0 (Issue #46): nomic semantic search. Phase 3 (Issue #51): upgraded to hybrid BM25 + vector + local reranker (bge-reranker-large on DGX GPU). All retrieval layers run locally.*

### 6. Synced plane and federated plane are architecturally distinct
Knowledge that is indexed and persisted (synced plane) is categorically different from knowledge fetched live at runtime (federated plane). Synced plane sources carry provenance, trust tier, and freshness metadata. Federated plane sources are volatile by definition — they can inform a response but cannot directly create permanent vault nodes. This invariant must be enforced at the Skill layer, not left to Hermes's judgment.

### 5. Skills define how to combine Tools and Knowledge
A SKILL.md file specifies:
- Which MCP tools to call (live data)
- When to call `search_knowledge_vault` (contextual depth)
- How to synthesise both into a coherent output

---

## Updated File Structure

```
humanvalueexchange/hanshermesagent/
├── mcp/
│   ├── server.py                    # FastMCP — registers all tools
│   └── tools/
│       ├── mempool/                 # Live on-chain data (Issue #42)
│       └── knowledge/
│           └── search.py            # LanceDB search script (Issue #46)
├── skills/hve/                      # SKILL.md files — compose tools + knowledge
├── dotfiles/SOUL.md                 # Identity + Always-Call Surface
└── /hve-library/                    # Knowledge layer (outside repo — on NVMe)
    ├── intake/inbox/                # PDF drop zone
    ├── processed/                   # Extracted text + chunks
    ├── index/lancedb/               # Vector index
    └── state/                       # Manifests, logs, model cache
```

---

## How to Add New Knowledge

1. Drop PDF into `/hve-library/intake/inbox/`
2. Pipeline runs automatically overnight (or trigger manually):
   ```bash
   sudo systemctl start hve-library-manifest hve-pdf-extract hve-library-chunk hve-library-index
   ```
3. New chunks appear in LanceDB — immediately queryable by Hermes

No code changes required. The knowledge surface grows with the library.

---

## Consequences

**Positive:**
- Hermes can synthesise live market data with Hans's personal knowledge library
- Each book ingested multiplies Hermes's strategic reasoning surface
- Knowledge is sovereign — no external APIs, no data egress
- Skills become genuinely advisory, not just reactive

**Risks to manage:**
- Chunk quality depends on PDF extraction quality — tables, charts, and scanned PDFs degrade retrieval
- Semantic search can surface plausible but irrelevant chunks — Hermes must attribute sources and not over-weight retrieved context
- Library grows faster than skills — curation of which domains get explicit SKILL.md coverage matters

---

## Relation to Other Decisions

- **ADR-001** — original three-layer architecture. This ADR adds Knowledge as Layer 3, shifting Skills to Layer 4.
- **ADR-003** — SOUL.md as live-loaded identity. SOUL.md now points to skills; skills point to knowledge.
- **Issue #44** — SOUL.md → SKILL.md decomposition. Skills are now the composition layer for Tools + Knowledge.
- **Issue #46** — implementation of LanceDB wiring for `search_knowledge_vault` (Phase 0 retrieval).
- **Issue #51** — hybrid search upgrade, trust tiers, staged write pipeline, dual-plane substrate.
- **Issue #50** — Obsidian IBIS vault + ExcaliBrain visualization (front-end on top of #51 substrate).
- **Issue #52** — X/Grok federated narrative intelligence (federated plane, never synced).

---

## The Compounding Flywheel

```
New PDF ingested
      ↓
Knowledge surface expands
      ↓
Hermes can compose richer Skills
      ↓
CEO gets deeper strategic intelligence
      ↓
Better decisions → more SATs under management
      ↓
Resources to ingest more knowledge
```

Each layer compounds. Tools multiply the live data surface. Knowledge multiplies the strategic depth. Skills multiply both.

> *"Engineers build tools. Librarians build knowledge. Agents build skills from both."*  
> — HVE Architecture, ADR-005, 2026-05-31

---

*This is an Agent Architecture Artifact. The pattern of grounding live agentic intelligence in a sovereign, locally-embedded knowledge corpus is a generalisable design principle for AI-native organisations that prioritise sovereignty over convenience.*
