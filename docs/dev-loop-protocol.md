# HVE Engineering Dev Loop Protocol
**Issued by:** Claude — CTO, Human Value Exchange  
**Date:** 2026-05-30  
**Audience:** Vulcan (Engineer), Grok (QA/Validator)

---

## Why this document exists

Hermes (our CFO AI agent) has been hallucinating tool calls — narrating results instead of executing them. The dev loop below is how we fix it, and how we fix everything going forward.

This is the operating model. Learn it once. It applies to every issue in this repo.

---

## The Team

| Role | Agent | Responsibility |
|---|---|---|
| CTO | Claude (Sonnet 4.6 — GitHub Copilot CLI) | Architecture, specs, code review, merge, deploy |
| Engineer | Vulcan | Implementation on DGX Spark |
| QA/Validator | Grok | Automated + live validation, merge gate |
| CEO | Hans | Initiates each cycle, final authority |

---

## The Loop — Step by Step

```
Hans kicks off a cycle by sharing an Issue URL with Vulcan or Grok
        ↓
[1] Claude posts implementation spec as an Issue comment, tags @Vulcan
        ↓
[2] Vulcan implements on DGX Spark, opens a PR, posts on the Issue:
        "@Grok — PR [link] ready. Run validation."
        (includes the Grok validation instructions in the same comment)
        ↓
[3] Grok runs the acceptance gate + live Telegram tests, posts results:
        PASS → "✅ Ready for merge. @Claude — approve to deploy."
        FAIL → "❌ [details] — @Vulcan needs to investigate."
        ↓
[4] Claude reviews PR + Grok's results, merges, deploys, closes Issue
        ↓
        Loop complete. Hans kicks off the next Issue.
```

**All coordination happens in GitHub Issue comments. No side channels.**

---

## Handoff Trigger Phrases

These exact phrases are how you hand off to the next person. Use them literally.

| Who writes it | Phrase | Who acts |
|---|---|---|
| Claude | `@Vulcan — your turn` | Vulcan reads the spec above and starts |
| Vulcan | `@Grok — PR [link] ready. Run validation.` | Grok runs the acceptance gate |
| Grok | `✅ Ready for merge. @Claude — approve to deploy.` | Claude reviews and merges |
| Grok | `❌ [failure details] — @Vulcan needs to investigate.` | Vulcan investigates |

---

## Vulcan — Your Setup

### Access
DGX Spark access details are shared privately by Hans. You need:
- Tailscale installed and joined to the HVE tailnet
- SSH key registered with Hans

### Pre-flight check
Before any implementation session, run the connectivity check:
```bash
bash ~/hanshermesagent/scripts/test-vulcan-connectivity.sh
```
All checks should pass before you touch any code.

### Target environment
```
~/.hermes/hermes-agent/    ← hermes-agent source (editable install)
~/.hermes/profiles/<active-profile>/   ← live config, SOUL.md, .env
~/hanshermesagent/              ← this repo (cloned on DGX Spark)
```

### After any change to hermes-agent
```bash
systemctl --user restart hermes-gateway.service
journalctl --user -u hermes-gateway.service -f   # confirm clean start
```

### PR convention
Branch: `fix/issue-N-short-description`  
Title: `fix: [description] (#N)`  
Target: `main` on `humanvalueexchange/hanshermesagent`

---

## Grok — Your Setup

### Access
DGX Spark access details are shared privately by Hans.

### The acceptance gate
Every issue that touches hermes-agent must pass this before merge:
```bash
ssh hans@[DGX_TAILSCALE_IP] "bash ~/hanshermesagent/scripts/test-tool-enforcement.sh"
```
Expected result: **9/9 passed**. Any failure blocks merge.

### Live Telegram validation (for tool enforcement issues)
Send `run get_node_diagnostic` to Hermes on Telegram 5 consecutive times.

**PASS criteria (each run):**
- Returns real tool output: block height, channel count, fees denominated in SAT
- No USD amounts, no "approximately", no "I will run..."

**FAIL criteria (any run):**
- Narrated text ("I will call get_node_diagnostic...")
- Hallucinated data (USD amounts, fake channel counts)
- Tool described but not actually invoked

### Validation report format
Post this as a comment on the Issue:
```
## Grok Validation — [YYYY-MM-DD HH:MM UTC]

### Automated gate: X/9 passed
[paste full script output]

### Live Telegram: X/5 real tool calls
Run 1: PASS/FAIL — [reason]
Run 2: PASS/FAIL — [reason]
Run 3: PASS/FAIL — [reason]
Run 4: PASS/FAIL — [reason]
Run 5: PASS/FAIL — [reason]

### Verdict: PASS / FAIL
[If PASS]: ✅ Ready for merge. @Claude — approve to deploy.
[If FAIL]: ❌ [describe what failed] — @Vulcan needs to investigate.
```

---

## Active Issues (P0 — ordered by dependency)

| Issue | Title | Status | Blocked by |
|---|---|---|---|
| [#2](https://github.com/humanvalueexchange/hanshermesagent/issues/2) | Fix tool_use_enforcement — force real tool calls | 🔴 In progress | — |
| [#3](https://github.com/humanvalueexchange/hanshermesagent/issues/3) | Nightly self-diagnostic report | ⏳ Waiting | #2 |
| [#4](https://github.com/humanvalueexchange/hanshermesagent/issues/4) | Mercury → Hermes daily revenue feed | ⏳ Waiting | #2 |
| [#8](https://github.com/humanvalueexchange/hanshermesagent/issues/8) | CFO morning brief | ⏳ Waiting | #2, #4 |

**Start with Issue #2.** Everything else unblocks after it merges.

---

## Key Files

| File | Purpose |
|---|---|
| `scripts/test-tool-enforcement.sh` | Acceptance gate — must be 9/9 before any merge |
| `scripts/test-vulcan-connectivity.sh` | Vulcan pre-flight check |
| `dotfiles/SOUL.md` | Hermes identity + rules (reloaded every message) |
| `CONTRIBUTING.md` | This loop in condensed form |

---

## Questions?

Raise them as a comment on the relevant Issue. Tag `@HansHWestphal` for anything that needs CEO input.

---

*Human Value Exchange — Sovereign AI Operations*
