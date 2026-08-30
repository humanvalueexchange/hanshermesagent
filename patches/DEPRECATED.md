# patches/ — DEPRECATED

This directory is retained for historical reference only.

The `patches/` convention (recording deployed diffs as `.patch` files) has been
**officially deprecated** as of 2026-05-30.

**See:** [ADR-004 — patches/ Convention Deprecated](../docs/adr/ADR-004-patches-deprecation.md)

## Why deprecated

- Git commit history provides a complete, authoritative audit trail of all changes
- GitHub Issues serve as the structured change record (what changed, why, who decided)
- Manual patch files created duplicate/stale records with no enforcement mechanism
- The `hermes-deploy.sh` script's `--dry-run` flag covers the "what will change" use case

## Audit trail going forward

| Layer | Tool | Where |
|---|---|---|
| Code changes | `git log` / `git diff` | `humanvalueexchange/hanshermesagent` repo |
| Decision record | GitHub Issues + ADRs | `docs/adr/` |
| Live deploy diff | `scripts/hermes-deploy.sh --dry-run` | Run before any deploy |
| Config snapshots | Timeshift (daily) | DGX Spark NVMe |
