---
name: hermes-critic
description: "Primary-model risk gate using CONDUCTOR:APPROVE / CONDUCTOR:VETO under the current local Hermes model stack."
category: trading
version: 2.0
date: 2026-05-30
deprecated_model: gemma2:27b
active_model: qwen3.5:27b-128k (Primary)
---

# hermes-critic — Critic, Risk & Veto (Conductor-Inline)

## Architecture Change (2026-05-30)

The veto function is performed inline by the primary model
(`qwen3.5:27b-128k`). It synthesizes research output and makes the Go/No-Go
decision before any execution workflow.

> `gemma2:27b` remains installed on the DGX and is available for Open WebUI debug sessions (short, controlled, < 8K total) only.

## Current Decision Flow

```
1. Research  →  qwen3.5:27b-128k → market analysis + strategy
2. Primary  →  qwen3.5:27b-128k → synthesize + CONDUCTOR:APPROVE or CONDUCTOR:VETO
3. Execution → gpt-oss:20b/qwen2.5:3b → position math + audit trail (only on APPROVE)
```

## Veto Rules (enforced by Conductor)

- Max risk per trade: **1% of portfolio**
- Daily drawdown limit: **2%**. Weekly: **5%**. Breach → halt all trading, alert Hans.
- Kraken taker fee **0.26%** must be factored into net edge — negative net edge = VETO
- **Paper trading only** until Hans explicitly authorizes live trading in writing
- Bitcoin/BTC only. No altcoins.

## Approval Token

```
CONDUCTOR:APPROVE — [one sentence reason]
```
or
```
CONDUCTOR:VETO — [one sentence reason: which rule was violated]
```

**Hard rule:** If the Conductor's response does not contain `CONDUCTOR:APPROVE`, treat it as `CONDUCTOR:VETO`. No override.
