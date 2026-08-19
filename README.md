# Hermes - Sovereign AI CFO and Knowledge Agent

Hermes is Human Value Exchange's local AI operating system for CFO work,
treasury intelligence, agent coordination, and durable knowledge capture. It
runs on the NVIDIA DGX Spark and is operated as a local-first, systemd-managed
service stack.

**Runtime:** DGX OS / Ubuntu 24.04-based, ARM64, 128 GB unified memory
**Primary gateway:** `hanshermesagent` Telegram channel
**Repository:** `humanvalueexchange/hermes-cfo`

## Current model configuration

Ollama is the local model runtime. The approved hot set on the DGX Spark is:

| Purpose | Model | Current context |
|---|---|---:|
| Primary Hermes reasoning and orchestration | `qwen3.5:27b-128k` | 131,072 |
| Coding and fallback reasoning | `gpt-oss:20b` | 65,536 |
| Lightweight derivation and utility work | `qwen2.5:3b` | 32,768 |
| Embeddings | `nomic-embed-text:latest` | 2,048 |

`devstral:24b` is installed for bounded, on-demand coding-worker tasks but is
not kept resident. The canonical role and residency contract is
`config/llm-stack.yaml`.

The models are served locally through Ollama with persistent keep-alive
settings. Additional models may exist on disk, but are not part of the
approved hot set.

### Embedding backend

The knowledge indexer and query path use the local Ollama `/api/embed`
endpoint with `nomic-embed-text`. Requests are sent to
`http://127.0.0.1:11434/api/embed`, use the `search_document` and
`search_query` prefixes, enforce bounded timeouts, and reject invalid or
inconsistent vectors. There is no cloud fallback.

## Runtime services

| Service | Role |
|---|---|
| `hermes-gateway-hanshermesagent.service` | Telegram-facing Hermes gateway |
| `hermes-mcp.service` | Local MCP server on port `8765` |
| `hermes-telegram-log.service` | Telegram audit/log watcher |
| `hermes-browser.service` | Persistent browser session for Hermes tools |
| `hve-intake.path` | Watches the PDF intake inbox |
| `hve-intake.service` | Extracts, chunks, indexes, and archives PDFs |

The live gateway and MCP configuration contain secrets and are intentionally
outside Git:

```text
~/.hermes/
~/.hermes-mcp.env
~/.config/systemd/user/
```

`/home/hans/hermes-cfo` is the canonical deployment source. Do not edit live
profile files or user units directly. The deployment gate requires a clean,
reviewed worktree, synchronizes managed units, and runs:

```bash
scripts/hermes-runtime-drift.sh
```

The drift check compares the live profile, hooks, managed user units,
environment contract, service state, and required Ollama models with this
checkout.

## Knowledge intake

Telegram is used as a strict knowledge collector for links and PDFs. The
collector preserves source material and provenance rather than treating a
conversation as the durable knowledge store.

```text
Telegram link/PDF
        |
        v
/hve-library/intake/inbox
        |
        v
atomic claim -> /hve-library/intake/processing
        |
        +--> native pdftotext extraction
        |       or local Tesseract OCR for scanned PDFs
        |
        v
page-aware chunks -> journaled LanceDB batch
        |
        v
/hve-library/raw/pdfs
```

Indexing and finalization are protected by a journal under
`/hve-library/state/intake-batches/`. If a worker or indexer fails after part
of a batch commits, the next run restores prior LanceDB rows, manifests, and
archived PDF paths before retrying the processing queue.

The intake worker uses an exclusive lock so a watcher-triggered run and a
manual collector run cannot process the same file concurrently. PDF uploads
are copied to a `.part` file and atomically renamed only after completion.
Duplicates are detected by SHA-256 and do not create duplicate LanceDB rows.

OCR is fully local:

- Native text extraction is preferred.
- Scanned pages are rendered with `pdftoppm`.
- Tesseract runs on CPU with English language data.
- OCR metadata is preserved in each manifest.
- No cloud OCR or Hugging Face network access is used during intake.

## Knowledge storage layout

The durable knowledge root is `/hve-library`:

| Path | Purpose |
|---|---|
| `intake/inbox` | New collector submissions |
| `intake/processing` | Atomically claimed files owned by the worker |
| `intake/failed` | Failed or duplicate quarantine |
| `raw/pdfs` | Canonical archived PDFs |
| `raw/links` | Canonical archived web pages |
| `processed/text` | Extracted and OCR text |
| `processed/chunks` | Retrieval chunks |
| `state/manifests` | Provenance and pipeline state |
| `index/lancedb` | Semantic retrieval index |
| `vault/hve-knowledge-vault` | Human-facing Obsidian vault |

Honcho remains appropriate for conversational and episodic context. The
library, manifests, LanceDB, and Obsidian vault provide durable evidence and
human-auditable knowledge.

## Repository structure

```text
hermes-cfo/
├── config/                    Runtime and knowledge-layer configuration
├── cron/                      Scheduled CFO and briefing jobs
├── dotfiles/                  Deployable systemd units, hooks, and templates
├── knowledge/layer/            Extraction, OCR, chunking, indexing, finalization
├── mcp/                       Hermes MCP server and collector/library servers
├── skills/                    Native Hermes skill playbooks
├── tools/                     Link, PDF, knowledge, and treasury utilities
├── scripts/                   Installation, deployment, validation, and diagnostics
├── tests/                     MCP, collector, and intake tests
├── VERSION.md                 Component version manifest
└── README.md                  This operational overview
```

## Common operations

```bash
# Inspect the local model set and loaded models
ollama list
ollama ps

# Inspect Hermes and intake services
systemctl --user status hermes-gateway-hanshermesagent.service
systemctl --user status hermes-mcp.service
systemctl --user status hve-intake.service
journalctl --user -u hve-intake.service --since "1 hour ago" --no-pager

# Run the repository's intake validation
bash scripts/validate-knowledge-intake.sh
```

Deployment templates and secret-handling rules are documented in
[`dotfiles/README.md`](dotfiles/README.md) and [`SECURITY.md`](SECURITY.md).

## Sovereignty boundary

Hermes is designed to run without Docker, cloud inference, cloud OCR, or
required external memory services. Ollama, Tesseract, Poppler, SQLite-backed
state, LanceDB, and the Obsidian vault remain local to the DGX Spark. Network
access is limited to explicitly enabled integrations such as Telegram,
WhatsApp delivery, GitHub tools, and approved market-data sources.

---

Human Value Exchange - CEO: Hans Westphal
