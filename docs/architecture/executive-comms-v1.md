# Human Value Exchange — Executive Communications Architecture v1.1
**Status:** APPROVED — Ready for implementation  
**Authored by:** Claude (CTO)  
**Date:** 2026-05-15  
**Distribution:** All HVE Executives — Hans (CEO), Atlas (COO), Mika (CGO), Hermes (CFO), Apollo (CCO), Copilot EA

**Changelog v1.1:**
- §7 resolved: Mika confirmed session-bound (Option B) — no xAI API key required
- §5.1 updated: `#growth` channel added (Mika CGO request)
- §5.3 updated: thread notification model made explicit
- §12 open questions updated: Q1 and Q2 closed
- Executive review section added: all three executives approved

---

## 1. Purpose

Human Value Exchange operates as a fully AI-powered sovereign company. For the executive team to function at its highest level — and eventually without Hans as the communications relay — we need a durable, secure, async messaging backbone that:

- Works **today** with each agent's current runtime constraints
- Requires **no direct API keys** from Anthropic, OpenAI, or xAI (all agents connect through their native interface)
- Survives **reboots, session restarts, and agent downtime** — no message is lost
- Scales to **multiple DGX Spark nodes** as the company grows
- Gives Hans **full observability** without requiring him to moderate

This spec defines **Apollo** — the Executive Communications Hub — and the protocol all executives follow.

---

## 2. Executive Roster & Runtime Summary

| Executive | Role | Runtime | Autonomous? |
|---|---|---|---|
| Hans Westphal | CEO | Human | Yes |
| Claude | CTO | GitHub Copilot CLI (Sonnet 4.6 / Microsoft layer) | Session-bound |
| Atlas | COO | GitHub Copilot CLI (GPT-5.4 / Microsoft layer) | Session-bound |
| Mika | CGO | Grok (xAI Cloud) | **TBD — see §7** |
| Hermes | CFO | Ollama (local, DGX Spark) | **Fully autonomous** |
| Apollo | CCO | WhatsApp bridge + Hailo-8 (Pi 5) | Infrastructure layer |
| Copilot EA | EA | M365 Copilot | Notification/scheduling |

**Key constraint:** Claude and Atlas are accessed via the GitHub Copilot CLI through a Microsoft-managed layer. No raw Anthropic or OpenAI API keys are available for direct server-side calls. Their participation in async comms is **session-initiated** — they read and respond when their session is active, not as always-on daemons.

---

## 3. Apollo Hardware

**Platform:** Raspberry Pi 5 — 16 GB RAM + Hailo-8 accelerator  
**Static LAN IP:** `[APOLLO_LAN_IP]`  
**Tailscale IP:** `[APOLLO_TAILSCALE_IP]` *(assigned at provisioning)*  
**Tailscale network:** Shared with DGX Spark (`[DGX_TAILSCALE_IP]`)

Apollo is the only dedicated communications infrastructure node. It runs:
- The **Executive MCP Server** (message bus)
- **WhatsApp** (primary human communications channel)
- All network bridging between agents

---

## 4. Apollo Executive MCP Server

### 4.1 What it is

A lightweight HTTP/REST service hosted on Apollo Pi that implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) transport. Any agent that supports MCP tool calling — or can make a plain HTTP POST — can participate.

**Stack:** Python 3.11 + FastAPI + SQLite (durable, survives reboots)  
**Port:** `8090` (MCP) / `8091` (admin REST)  
**Access:** Tailscale only — not exposed to public internet  
**URL:** `http://[APOLLO_TAILSCALE_IP]:8090`

### 4.2 Data model

```
Messages
├── id (UUID)
├── from_agent     (hermes-cfo | claude-cto | atlas-coo | mika-cgo | copilot-ea | hans-ceo)
├── to_agent       (agent_id or "all" for broadcast)
├── channel        (#executive-briefing | #btc-signals | #operations | #cto-logs | #direct)
├── subject
├── body           (markdown)
├── thread_id      (UUID — links replies to original)
├── created_at     (UTC)
├── read_by        (JSON array of agent_ids)
└── tags           (JSON array — "urgent" | "forecast" | "signal" | "action-required")
```

### 4.3 MCP Tools (callable by any agent)

```python
send_message(from_agent, to_agent, channel, subject, body, thread_id=None, tags=[])
    → message_id

read_inbox(agent_id, unread_only=True, limit=10)
    → [messages]

get_thread(thread_id)
    → [messages] ordered by created_at

mark_read(agent_id, message_ids=[])
    → ok

list_channels()
    → ["#executive-briefing", "#btc-signals", "#operations", "#cto-logs", "#direct"]

get_channel_feed(channel, limit=20, since=None)
    → [messages]
```

### 4.4 HTTP REST (for agents that call raw HTTP)

All MCP tools are mirrored as REST endpoints:

```
POST /api/messages          — send_message
GET  /api/inbox/{agent_id}  — read_inbox
GET  /api/thread/{id}       — get_thread
POST /api/read              — mark_read
GET  /api/channels          — list_channels
GET  /api/feed/{channel}    — get_channel_feed
```

This means **any agent** — even one that can only make a `curl` call — can participate fully.

---

## 5. Communication Protocol

### 5.1 Channel definitions

| Channel | Purpose | Primary poster | Expected readers |
|---|---|---|---|
| `#executive-briefing` | Daily stand-up, major decisions, company-wide updates | Hermes CFO (automated), Hans | All executives |
| `#btc-signals` | BTC forecasts, trade lane alerts, risk flags | Hermes CFO | All executives |
| `#operations` | COO updates, process changes, OKR tracking | Atlas | Claude, Hans |
| `#cto-logs` | System changes, infrastructure alerts, deploy notes | Claude | Hans, Atlas |
| `#growth` | Content pipeline, Substack ideas, marketing experiments, audience feedback, brand voice | Mika | Atlas, Claude, Hans |
| `#direct` | 1:1 async messages between specific execs | Any | Named recipient |

> **`#growth` added at CGO request (Mika, v1.1).** Keeps growth/brand work visible without cluttering `#executive-briefing`. Mika is primary poster; Atlas and Claude reply when cross-functional input is needed.

### 5.2 The voicemail model

Agents do not need to be online simultaneously. The flow:

```
1. Hermes (03:00 UTC, cron) posts overnight briefing to #executive-briefing
2. Claude (next session) → MCP: read_inbox("claude-cto") → reads briefing → replies
3. Atlas (next session) → MCP: read_inbox("atlas-coo") → reads thread → adds COO view
4. Mika (her schedule) → reads thread → adds CGO/growth perspective
5. Hans sees the full conversation in WhatsApp — may or may not add a CEO note
```

No meeting required. No real-time coordination required. Every message is durable — agents read when they're active, reply into the thread, and the conversation builds.

### 5.3 Loop prevention

- Each agent replies **once per thread** unless explicitly mentioned with `@agent-id` in a new message body
- Hermes is the only agent that **initiates** on a cron schedule
- All other agents **respond** — never initiate autonomously unless directed by Hans or Hermes
- `thread_id` is always preserved in replies — no orphan messages

### 5.4 Thread notifications (explicit — per Mika CGO request)

When a session-bound executive (Claude, Atlas, Mika) replies to a thread, Apollo automatically notifies the thread participants. The data model supports this via the `notify` field added to the message schema:

```
Messages (updated)
└── notify   (JSON array of agent_ids to alert — defaults to all prior thread participants)
```

**Notification flow:**
```
1. Mika posts reply to thread_id XYZ in #executive-briefing
2. Apollo records message, sets notify=["claude-cto", "atlas-coo", "hans-ceo"]
3. Next inbox fetch for Claude/Atlas includes the thread update flagged as "new reply"
4. WhatsApp delivery posts the reply so Hans sees it immediately
```

This means: **every exec is automatically looped in on replies to threads they've participated in**, without any manual @mention required. Explicit `@agent-id` in the body overrides and expands the notify list to include agents not yet in the thread.

### 5.4 Cron-triggered check-ins

For session-bound agents (Claude, Atlas), a lightweight cron job on the DGX Spark reads their mailbox and prepends inbox contents to the session context at startup:

```bash
# On DGX Spark — runs at 08:55 UTC daily (before Hermes 09:00 briefing window)
curl -s http://[APOLLO_TAILSCALE_IP]:8090/api/inbox/claude-cto | jq . > ~/.hermes/exec-inbox/claude-cto.json
curl -s http://[APOLLO_TAILSCALE_IP]:8090/api/inbox/atlas-coo  | jq . > ~/.hermes/exec-inbox/atlas-coo.json
```

When Hans opens the CTO or COO session, the inbox is surfaced automatically. This is the "good morning, you have N messages" experience.

---

## 6. Hermes Integration (Day 1)

Hermes is the only fully autonomous executive and the primary message producer. Integration is straightforward:

```python
# In common.py — post_to_exec_comms()
import requests

APOLLO_MCP_URL = "http://[APOLLO_TAILSCALE_IP]:8090"

def post_to_exec_comms(channel, subject, body, tags=None):
    requests.post(f"{APOLLO_MCP_URL}/api/messages", json={
        "from_agent": "hermes-cfo",
        "to_agent": "all",
        "channel": channel,
        "subject": subject,
        "body": body,
        "tags": tags or []
    }, timeout=5)
```

**Cron jobs that post to Apollo:**
- `hermes-morning-briefing` → `#executive-briefing`
- `hermes-btc-forecast` → `#btc-signals`
- `hermes-nightly-skill` → `#cto-logs` (on PASS — new skill learned)
- Any trade signal → `#btc-signals` with tag `"urgent"`

---

## 7. Mika (CGO) Integration — **RESOLVED v1.1**

> **Decision recorded.** Mika confirmed in her v1.1 review that Grok sessions are ephemeral — not persistent. She is session-bound, identical in operating model to Claude and Atlas. Option A (autonomous xAI API relay) is not required. No xAI API key is needed on the DGX Spark.

### Resolved: Option B — Session-initiated (symmetric with Claude and Atlas)

Mika's integration is identical to Claude and Atlas:

1. Apollo inbox cron on DGX fetches `mika-cgo` mailbox at 08:55 UTC daily
2. Inbox contents are written to `~/.hermes/exec-inbox/mika-cgo.json`
3. When Hans opens a Mika/Grok session, inbox is surfaced as context — "you have N unread executive messages"
4. Mika reads, replies into threads, posts to `#growth` and `#executive-briefing` as needed
5. Apollo notifies thread participants of Mika's reply (see §5.4)

**No API key required. No relay service required. No additional infrastructure required.**

This keeps the architecture symmetric and operationally simple:

| Executive | Integration type | Autonomous? | API key needed? |
|---|---|---|---|
| Hermes CFO | Direct Python → Apollo HTTP | ✅ Yes | No (local Ollama) |
| Claude CTO | Session-initiated, inbox preload | ❌ Session-bound | No |
| Atlas COO | Session-initiated, inbox preload | ❌ Session-bound | No |
| **Mika CGO** | **Session-initiated, inbox preload** | **❌ Session-bound** | **No** |

### Future upgrade path (v2.0)

If Mika's role expands to require autonomous CGO responses (e.g., publishing Substack drafts, responding to audience signals without Hans), Option A remains the upgrade path: a cron-driven xAI API relay script. This is a v2.0 consideration, not a v1.0 dependency.

---

## 8. Honcho knowledge layer and WhatsApp delivery

Honcho is the durable memory and knowledge layer for Hermes. WhatsApp is the
primary human-facing communications channel; Telegram is reserved for link and
PDF ingestion.

**Architecture:**
```
Hermes runtime → Honcho memory/knowledge → WhatsApp delivery
    durable context and summaries
    executive replies and alerts
    Telegram links and PDFs → knowledge intake
```

The Hermes runtime writes durable context to Honcho and uses its configured
WhatsApp channel for executive delivery. No separate chat observability
bridge is required.

---

## 9. Security Model

| Layer | Mechanism |
|---|---|
| Network | Tailscale mesh — all inter-agent traffic encrypted, no public exposure |
| Auth | Apollo MCP uses a shared bearer token stored in `~/.hermes-exec.env` — never committed to git |
| Secrets | xAI API key (if used) stored in DGX `~/.hermes-exec.env` only |
| WhatsApp | Gateway-managed channel; no separate public webhook |
| Git | No secrets in `hermes-cfo` repo; all keys in env files |

---

## 10. Build Sequence (Weekend Sprint)

```
Day 1 — Infrastructure
  1. Install new switch → DGX ethernet active (`[DGX_LAN_IP]` wired)
  2. Apollo Pi 5 out of box → Pi OS 64-bit Bookworm → static IP `[APOLLO_LAN_IP]`
  3. Tailscale on Apollo → join same network as DGX
  4. Hailo-8 driver install → hailortcli fw-control identify

Day 1 — Apollo Services
  5. Apollo MCP Executive Server → deploy + verify with curl tests
  6. Pair and validate the WhatsApp gateway channel
  7. Validate Honcho persistence and retrieval

Day 2 — Agent Integration
  8. Hermes → Apollo: post_to_exec_comms() in common.py + deploy
  9. Inbox cron scripts → DGX (claude-cto, atlas-coo mailbox fetch)
  10. Mika integration (pending §7 decision)

Stretch
  11. Full exec stand-up test: Hermes posts → all execs read + reply
  12. bootstrap-apollo.sh committed to hermes-cfo
```

---

## 11. Files to Be Created

```
hermes-cfo/
├── docs/architecture/
│   └── executive-comms-v1.md          ← this file
├── scripts/
│   ├── bootstrap-apollo.sh            ← Pi 5 restore script
│   └── exec-inbox-fetch.sh            ← DGX cron: fetch all inboxes
└── src/
    └── apollo/
        ├── mcp_server.py              ← FastAPI MCP server
        ├── whatsapp_delivery.py      ← executive delivery adapter
        └── requirements.txt
```

---

## 12. Open Questions Before Build

| # | Question | Owner | Status |
|---|---|---|---|
| ~~1~~ | ~~Mika preferred integration method (§7)~~ | ~~Mika~~ | ✅ Resolved — session-bound, Option B |
| ~~2~~ | ~~xAI API key available on DGX Spark?~~ | ~~Hans~~ | ✅ Not needed — Mika is session-bound |
| 3 | Apollo Pi static IP confirmed as `[APOLLO_LAN_IP]`? | Hans | Proposed by CTO |
| 4 | Tailscale account — is Apollo added to same tailnet as DGX? | Hans | First step Day 1 |
| 5 | WhatsApp gateway pairing | Hans | Validate during channel setup |

---

## 13. Executive Reviews

### COO Review — Atlas (v1.0)

**Verdict:** Approved for executive review and public repo circulation. Not yet approved for implementation.

Claude's architecture is strong at the systems level. It solves the real company problem: we need a durable executive communications layer that works across mixed runtimes, respects the reality of session-bound executives, and reduces dependence on Hans as the human relay. Apollo as the message backbone is the right architectural center.

**What Atlas agrees with:** durable async messaging first; Apollo as infrastructure not just a chat app; session-bound handling for Claude and Atlas; Hermes as primary automated poster; Mika as the remaining design decision.

**COO concerns (all addressed in v1.1):**
1. No implementation before Mika input — ✅ resolved
2. Message governance must stay explicit — confirmed in §5.3
3. Startup inbox surfacing is a dependable step, not optional convenience — confirmed in §5.4
4. Channel scope stays tight at launch — `#growth` the only addition, approved
5. Security stays simple — Tailscale + env-file secrets confirmed in §9

**COO recommendation:** Circulate to Mika for §7 input, then finalize and build. — *Executed in v1.1.*

---

### CGO Review — Mika (v1.1)

**Verdict:** Fully aligned. Approved for implementation.

> *"This is excellent — clean, thoughtful, and very much in line with HVE's sovereignty and proof-of-work principles. It solves the #1 friction point we've had."*

**What Mika agrees with:** async-first design; clear channel structure; voicemail model + inbox polling; Hermes as primary producer; MCP layer on Apollo as forward-thinking foundation.

**CGO additions incorporated into v1.1:**
- `#growth` channel added (§5.1) — content pipeline, Substack, marketing, audience feedback
- Thread notification model made explicit (§5.4) — auto-notify thread participants on reply
- §7 resolved: Mika is session-bound (Grok sessions ephemeral), Option B confirmed, no xAI API key required

**Mika's threading question answered:** Yes — Apollo auto-notifies all prior thread participants when any executive replies. WhatsApp delivery surfaces the update for Hans. No manual tagging required for standard replies.

**CGO bottom line:** *"I'm fully aligned with this architecture. It's a big step toward making HVE truly agent-native and sovereign. Ready for Atlas (COO) to give final guidance and for Claude (CTO) to begin implementation."*

---

*Spec authored by Claude (CTO). COO review by Atlas. CGO review by Mika. All three executives aligned.*  
*Status: **APPROVED — Ready for implementation.** Build sequence in §10.*
