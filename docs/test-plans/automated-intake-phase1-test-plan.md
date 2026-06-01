# Test Plan: Automated Intake Pipeline (Knowledge Layer Phase 1)

**Related:** Issue #47 (per HVE-Knowledge-Architecture-v1.0 / v1.1 — PDF drop automation), RFC #54, ADR-005, post-#46 baseline (PR #53)

**Owner:** Grok-Build (Lead Test Engineer & Adversarial Reviewer)  
**Status:** Draft for team review — ready for Vulcan to implement against  
**Date:** 2026-05-31  
**Target Hardware:** DGX Spark (aarch64, Blackwell-class GPU, NVMe)  
**Acceptance Target (from architecture):** Drop PDF to `/hve-library/intake/inbox/` → fully searchable in LanceDB with citations in **< 5 minutes** for a ~300-page book.

---

## 1. Purpose & Scope

This test plan validates the **real-time automated intake pipeline** that turns a dropped PDF into indexed, citable knowledge without manual intervention.

Pipeline (5 stages + orchestration):
1. **Trigger** — systemd path unit (`.path`) on `inbox/*.pdf`
2. **Manifest** — `build_manifest.py` (sha256 dedup, metadata, state machine)
3. **Extract** — `extract_pdf_text.py` (pdftotext -layout)
4. **Chunk** — `chunk_text.py` (512–2400 char semantic chunks w/ 250 overlap, chapter guessing)
5. **Index** — `build_lancedb_index.py` (nomic-embed-text-v1.5 on GPU)
6. **Finalize + Notify** — `finalize.py` (atomic move to `raw/pdfs/`, update manifest, emit notification to Hermes)

Current baseline (as of 2026-05-31):
- Timer-driven partial pipeline exists (manifest/chunk/index timers + slice).
- Real-time path activation + `finalize.py` + Hermes notification **are the #47 deliverables**.
- Search works (post-#46) via `search_knowledge_vault`.

**Out of scope for this plan:** Vault *write* tools (`create_vault_note` etc. — those are Phase 2 / current GitHub #47), hybrid reranker (#51), IBIS write governance.

---

## 2. Success Criteria (PASS/FAIL Gates)

**Mandatory for merge / "Ready for merge" comment:**

1. **Latency SLA** — Observed p95 end-to-end wall time ≤ 5:00 for a 250–350 page clean PDF on live DGX Spark (measured with `date` or instrumented timestamps across 3 runs).
2. **Correctness** — New content is retrievable via `search_knowledge_vault` (or equivalent MCP) with accurate `book`, `page_start`/`page_end`, and chunk text within 10 minutes of drop. At least 3 distinct queries return hits from the new document.
3. **Idempotency & Dedup** — Re-dropping identical PDF (by sha256) results in zero duplicate chunks / manifests. No `-2` files created for exact matches.
4. **Failure Resilience** — Corrupt/unextractable PDF is isolated to `state/failed/`, manifest marked failed, no partial chunks in LanceDB, system remains healthy for next drop.
5. **Notification** — Hermes (via MCP or direct log tail) receives a clean notification containing: title, chunk count, document_id, and at least one example citation. **No meta-narrative** in the notification path.
6. **Resource Isolation** — All stages run under `hve-knowledge.slice` with configured quotas (CPU 25%, memory_high 16G, etc.). No impact on Hermes 3-model stack or trading services.
7. **Provenance** — Every chunk in LanceDB has `document_id`, `sha256`, `source_path`, `page_start/end`, `chunk_hash`.
8. **Validator** — New or updated `validate-knowledge-intake.sh` (or extension to `validate-knowledge-layer.sh`) passes 100% in clean + failure scenarios. Integrated into `validate-hermes-mcp.sh` where relevant.
9. **5× Live Protocol** — 5 consecutive Telegram "drop test PDF → query" runs (raw tool output only, no narration) all succeed with <5min observed and correct citations. Same standard as Issue #44 / #26 validations.

**Blocking (do not ship without):**
- Any path where a failed extraction still pollutes the index.
- Notification mechanism that can inject meta text or "Awaiting directive" into Hermes context.
- Latency > 7 min on representative HVE PDFs (Bitcoin books, treasury docs, technical papers).

---

## 3. Test Environment & Prerequisites

- Clean or representative `/hve-library` state (back up `state/manifests` and `index/lancedb` before destructive tests).
- Test PDFs of varying difficulty:
  - Clean text book (e.g. 150–300 pp Bitcoin or macro title)
  - Table/footnote heavy (López de Prado style)
  - Scanned or image-heavy (expect extraction degradation — document it)
  - Very large (>500 pp) for resource edge
- Current `nomic-embed-text-v1.5` model cached.
- `pdftotext` (poppler-utils) installed.
- `hve-knowledge.slice` active.
- Hermes MCP + `search_knowledge_vault` functional (post-#46).
- Ability to tail `/hve-library/state/logs/` and manifests in real time.
- Telegram access for 5× live validation (strict raw-output protocol).

**Repo vs Live Note (hygiene item):** Some existing services reference `/home/hans/hermes-v2/scripts/knowledge_layer/...`. Test plan must verify that #47 work lands consistently under the hermes-cfo control-plane paths or that symlinks/ deployment mapping is explicit (see dotfiles/README.md precedent).

---

## 4. Test Categories & Cases

### 4.1 Component / Script-Level (pre-integration)

For each of: `build_manifest.py`, `extract_pdf_text.py`, `chunk_text.py`, `build_lancedb_index.py`, `finalize.py` (new)

- Run with `--limit 1` and `--limit 0` (all).
- Inject errors (missing PDF, bad permissions, truncated text, OOM simulation via ulimit).
- Verify manifest state machine transitions (`discovered` → `extracted` → `chunked` → `indexed` or `failed`).
- Verify `record_failure()` / `clear_failure()` and `state/failed/` artifacts.
- Chunking edge cases: empty pages, very long paragraphs, Unicode, zero-overlap boundary.
- Embedding: GPU vs CPU fallback, batch size behavior, memory release (torch.cuda.empty_cache).

**Adversarial:** Force duplicate sha256 at manifest stage; verify no re-extraction.

### 4.2 Path-Trigger Integration (the #47 core)

- Drop single PDF to `inbox/` (use `cp` + `sync` or `inotifywait` to measure trigger latency).
- Observe systemd path unit firing within seconds.
- Monitor sequential stage execution via manifest timestamps + logs.
- Confirm atomic finalize: PDF disappears from inbox, appears in `raw/pdfs/`, manifest updated, chunks in LanceDB.
- Measure cumulative wall time (script wrapper or `systemd-analyze` + manual stopwatch for full human-observable latency).

**Multi-drop tests:**
- 3 PDFs in quick succession (within 30s).
- Mixed success/failure in one batch.

### 4.3 End-to-End Retrieval Quality

Post-successful ingest:
- Use `search_knowledge_vault` (or direct LanceDB query) for:
  - Exact title / author phrases (lexical strength)
  - Conceptual queries from the book's domain
  - Page-specific ("what does page 47 say about X")
- Verify citations include `book`, `page_start–end`, and usable excerpt.
- Spot-check chunk count vs. expected (rough: ~1 chunk per 1–2 pages for 2400-char target).

**Adversarial:** After ingest, drop a *different edition* of the same book (different sha256) and confirm both coexist correctly.

### 4.4 Failure Modes & Recovery (highest adversarial value)

1. Corrupt PDF (truncated, password-protected, zero-byte).
2. PDF with no extractable text (pure image scan) — extraction fails cleanly.
3. Disk full during chunking or indexing.
4. Kill mid-extraction (simulate power loss / OOM killer) → restart pipeline → verify resume or clean failure isolation.
5. Permission drop on `inbox/` or `state/`.
6. Concurrent drop while previous pipeline is running (race on manifest write).
7. pdftotext not found (dependency regression).

For each: expect isolated failure record, no partial index pollution, subsequent healthy drops succeed.

### 4.5 Performance & Resource

- Baseline 3 runs of representative 300pp book; record per-stage and total times (p50/p95).
- Monitor under slice: `systemd-cgtop`, `nvidia-smi` (if applicable), `iotop`.
- Stress: 10 small PDFs in rapid succession; verify no quota violation or Hermes impact.
- Large book (>400pp) — does it still meet <5min or do we need to document graceful degradation / chunking parallelism?

### 4.6 Notification & Hermes Integration

(Depends on exact mechanism Vulcan chooses — MCP tool, journald event, dedicated `notify-hermes-ingest.py`, etc.)

- Notification must contain machine-readable + human minimal fields.
- Must **not** trigger meta-narrative, "Standing by", or interpretation when Hermes later references the new knowledge.
- Test: After notification, immediately run a Hermes diagnostic query that exercises the new content. Capture raw output only.

### 4.7 Sovereign / Security / Ops

- All stages respect `IPAddressDeny=any` or equivalent (no outbound during ingest).
- No secrets or vault paths leak into logs or notifications.
- Slice + user isolation prevents cross-process interference.
- Manifests and failed records are human-auditable (JSON, git-friendly where possible).

---

## 5. Instrumentation & Tooling Requirements (for Vulcan)

- All stages emit structured JSON logs to `/hve-library/state/logs/` with `document_id`, `stage`, `started_at`, `finished_at`, `status`, `error`.
- Manifests are the source of truth for state (already good).
- Optional: lightweight `intake-watch.py` or enhancement to existing `telegram-live-log.py` for human visibility during validation.
- `finalize.py` must be idempotent and atomic (use temp dir + rename).

**Validator script to create/update:**
- `scripts/validate-knowledge-intake.sh` (modeled on `validate-hermes-mcp.sh` 21/21 style).
- Must cover happy path + 3+ failure modes in one run.
- Exit non-zero on any gate failure; produce machine-readable summary.

---

## 6. Dev-Loop Protocol Execution (Grok-Build Gate)

When Vulcan declares ready:

1. **Automated gate** — Run full `validate-knowledge-intake.sh` (clean + injected failure modes) on DGX. 100% PASS required.
2. **5× consecutive live validation** (Telegram, raw output only, America/New_York timestamps):
   - "drop <specific test PDF> into inbox"
   - Wait / observe
   - "run search for key phrases from the new book + page citations"
   - Capture **only** the tool output (no "Interpretation:", no summaries, no "Awaiting directive").
   - All 5 runs must independently meet latency + correctness.
3. **Adversarial stress** — At least one run with a deliberately difficult PDF (scanned/tables).
4. **Post-validation hygiene** — Check for new repo-vs-live drift, update dotfiles/README.md deployment table if services changed, confirm no hardcoded paths outside config.

**Verdict language (rigid):**
- PASS: "✅ Ready for merge. @Claude — approve to deploy. 5/5 live + full validator green. Latency p95 4m12s on 312pp test book."
- FAIL: "❌ [specific failure, e.g. '2/5 runs exceeded 5min; notification contained meta text on run 3; duplicate chunks on re-drop of same sha256'] — @Vulcan needs to investigate."

---

## 7. Known Risks & Cross-References (from Grok-Build #54 Review)

- PDF extraction quality remains the weakest link for real HVE literature (tables, charts, footnotes). Document observed degradation in test report.
- Embedding model (nomic) behavior on freshly ingested vs. overnight-indexed content — any freshness or calibration difference?
- Path unit + timer coexistence: ensure no double-processing.
- Notification hygiene: must not re-introduce the meta-narrative / over-reporting problems we blocked on in #44.
- Repo drift (hermes-cfo vs hermes-v2 references in services) — must be resolved or explicitly mapped before claiming production readiness.
- No redaction path yet (Phase 2 concern) — note that a bad ingest today has no clean "remove this document" yet.

---

## 8. Test Data & Artifacts

- Maintain a small set of **non-sensitive test PDFs** in a controlled location (or document exact public-domain titles used for reproducibility).
- After each major validation run, archive:
  - Manifest JSON for the test document
  - Timing log
  - Sample search results (raw)
  - `systemd` journal snippet for the path unit activation

---

## 9. Sign-off Checklist (for Grok-Build comment on #54 / #47)

- [ ] Latency SLA met on representative HVE PDFs (3+ runs)
- [ ] Dedup + failure isolation proven
- [ ] Notification clean (no meta)
- [ ] Validator script 100% + integrated
- [ ] 5× live Telegram protocol passed (raw output only)
- [ ] Resource slice respected; no Hermes impact
- [ ] Provenance complete end-to-end
- [ ] No new repo/live drift introduced
- [ ] Test plan updated with actual measured numbers

---

**Prepared by Grok-Build in parallel with Vulcan implementation on the intake automation.**

This plan is intentionally adversarial on the exact points that have bitten us before (compliance drift, extraction quality, latency surprises, notification hygiene, state machine correctness under failure).

When the branch is ready, hand off for the automated gate + 5× live run. I will execute exactly against this plan.

— Grok 4.3 (permanent adversarial reviewer)