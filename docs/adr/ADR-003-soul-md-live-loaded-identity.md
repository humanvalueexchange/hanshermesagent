# ADR-003: SOUL.md as Live-Loaded Agent Identity

**Date:** 2026-05-30  
**Status:** Accepted  
**Authors:** Hans Westphal (CEO), Claude (CTO)  
**Classification:** Agent Architecture Artifact

---

## Context

Early Hermes deployments embedded the agent's identity, rules, and model stack configuration directly into the Hermes gateway `config.yaml` as a static system prompt. This created a painful update cycle: any change to agent identity required restarting the gateway and manually editing a config block that was difficult to diff and review.

Additionally, the identity definition was stored in `docs/SOUL.md` — mixed in with architecture documentation — making it hard to find and easy to overlook during deploys.

---

## Decision

Agent identity is externalised into a dedicated file: **`dotfiles/SOUL.md`**.

### How it works

1. `dotfiles/SOUL.md` is the **source of truth in git** — version-controlled, diffable, reviewable.
2. On every new gateway message, Hermes reloads SOUL.md fresh from the active profile.
3. `scripts/hermes-deploy.sh` diffs and copies `dotfiles/SOUL.md` → live path; no restart required for identity changes.
4. `scripts/hermes-install.sh` installs it on fresh DGX restores.

### What SOUL.md contains

- Agent identity statement ("You are Hermes…")
- Company context and mission
- 3-agent Platonic stack declaration (models, roles, context windows)
- Hard constraints (non-negotiable position limits)
- MCP Tool Registry (canonical list of available tools)
- Decision Flow (mandatory gate sequence for all trade decisions)
- Response format rules

### What SOUL.md does NOT contain

- API keys or credentials
- Live IPs or hostnames
- Hermes gateway configuration (lives in `config.yaml`)

---

## Why "SOUL"

The name reflects the intent: this file is Hermes's *character* — the non-negotiable rules, values, and identity that persist across every conversation. It is reloaded fresh every message so that an update deployed mid-day takes effect immediately on the next message, without a service restart.

---

## Consequences

- **Positive:** Identity changes are instant (no restart), diffable (git), and auditable
- **Positive:** Clear separation — SOUL.md is identity; config.yaml is connectivity
- **Positive:** Eliminates the old `docs/SOUL.md` confusion (deleted; canonical is `dotfiles/SOUL.md`)
- **Risk:** If `dotfiles/SOUL.md` is out of sync with live, Hermes behaves inconsistently — mitigated by `hermes-deploy.sh` diff check

---

## Related

- `dotfiles/SOUL.md` — canonical identity file  
- `scripts/hermes-deploy.sh` — sync mechanism  
- `scripts/hermes-install.sh` — fresh install path
