# Hermes CFO — Version Manifest
# Single source of truth for all component versions.
# Updated by Claude (CTO) on each component change.
# Grok Build and Vulcan: always test against the versions listed here.

## Live Stack (DGX Spark — [DGX_LAN_IP])

| Component | Version | Updated | Notes |
|---|---|---|---|
| **hermes-agent** | `0.15.2` | 2026-05-30 | v2026.5.29.2 tag — confirmed on 0.15.2 |
| **qwen3.8-hermes:27b-128k** | Ollama local | 2026-09-01 | Hard-capped primary reasoning/orchestration and tool use — 65K context |
| **qwen3.8-distill-2b:q4_k_m** | Ollama local | 2026-08-22 | Lightweight derivation — 32K context |
| **nomic-embed-text-v1.5** | Ollama local (`nomic-embed-text:latest` request alias) | 2026-08-25 | Knowledge embeddings — 768 dimensions; LanceDB contract aligned |
| **Open WebUI** | running | 2026-05-29 | Debug console only |
| **HVE MCP Server** | `1.0.0` | 2026-05-30 | hve-node at :8765 |

## Update Ownership

| Who | Responsibility |
|---|---|
| **Hermes (CFO AI)** | Daily version check via `scripts/hermes-update.sh` (cron 03:00) |
| **Hermes** | Telegram alert to Hans when update available (< 3 days old = notify, > 7 days = auto-upgrade) |
| **Claude (CTO)** | Approves major version upgrades, reviews security-tagged releases |
| **Grok Build** | Runs `test-tool-enforcement.sh` after every upgrade to confirm no regression |
| **Vulcan** | Builds against version in this file — always check VERSION.md before opening a PR |

## Update Policy

- **Daily**: Hermes checks PyPI at 03:00 UTC, notifies Hans via Telegram if behind
- **< 3 days old**: Notify only — allow team review of release notes
- **3–7 days old**: Notify with auto-upgrade countdown
- **> 7 days old**: Auto-upgrade, restart gateway, notify Hans, Grok Build runs tests
- **Security P0 releases**: CTO fast-tracks — upgrade same day

## Upgrade Log

| Date | From | To | Upgraded By | Notes |
|---|---|---|---|---|
| 2026-08-25 | `nomic-embed-text` contract alias | `nomic-embed-text-v1.5` canonical contract | Hermes-coder | Fixed Telegram LanceDB compatibility rejection; no index rebuild required |
| 2026-08-19 | Transformers/Hugging Face | Ollama `/api/embed` | Hermes-coder | Local 768-dim embeddings; full LanceDB reindex completed |
| 2026-05-30 | qwen3.5:27b | qwen3.5:9b | Claude (CTO) | Performance: 27b was over-provisioned for conductor role; 9b 6.6 GB vs 17 GB, same quality, frees 10 GB headroom |
| 2026-05-30 | gemma2:27b | qwen3.5:27b | Claude (CTO) | gemma2 8K ctx too small; qwen3.5:27b 262K ctx ✅ |
| 2026-05-29 | 0.13.0 | 0.15.2 | Claude (CTO) | Manual — discovered 22-day gap, daily cron now in place |
