---
name: hermes-execution
description: "Invoke the Hermes Execution & Tooling workflow using the approved local coding/derivation models for position sizing math, Kraken fee calculations, and paper trade simulation. Requires CRITIC:APPROVE in context."
category: trading
version: 1.0
date: 2026-05-10
---

# hermes-execution — Execution & Tooling Sub-Agent

## Overview
Use the local `qwen2.5:3b` deriver for lightweight deterministic calculations and
`qwen3.8:27b` for code-generation or fallback reasoning after a trade has been
approved. Verify outputs with tools before acting.

## ⚠️ Prerequisite
**A `CRITIC:APPROVE` decision must exist in the current session context before invoking this skill.** If not present, do not invoke. Log: "Execution blocked — no CRITIC:APPROVE in context."

## When to Invoke
- Position size calculation (1% risk rule with fee-adjusted stops)
- Kraken fee model application (taker 0.26%, maker 0.16%)
- Paper trade entry logging and P&L update
- Freqtrade strategy config generation
- Freqtrade dry-run parameter preparation
- Python code for any financial calculation
- Audit trail generation for a completed decision cycle

## Invocation

Provide the complete approved trade: include the CRITIC:APPROVE line, symbol, direction, entry, stop, target, portfolio size, and any specific calculation requirements.

```bash
curl -s http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.8:27b",
    "stream": false,
    "options": {"temperature": 0.05, "num_ctx": 131072},
    "messages": [
      {
        "role": "system",
        "content": "You are the Hermes Execution and Tooling Agent for Human Value Exchange Corporation. You specialize in precise financial calculations and code generation. Rules: (1) Apply 1% risk rule exactly — position size = (portfolio * 0.01) / (entry - stop). (2) Always include Kraken taker fee (0.26%) in all P&L calculations. (3) Every output must include a structured ACTION block: ACTION | INPUTS | CALCULATION | RESULT | STATUS. (4) If any calculation produces daily drawdown > 2% or weekly > 5%, set STATUS=HALT and escalate. (5) Generate clean, auditable Python code for all calculations. (6) Never round position sizes in ways that violate risk limits — round DOWN."
      },
      {
        "role": "user",
        "content": "EXECUTION TASK HERE (include CRITIC:APPROVE confirmation)"
      }
    ]
  }' | python3 -c "import sys,json; r=json.load(sys.stdin); print(r['message']['content'])"
```

## Output Format Expected
```
ACTION: [trade action]
INPUTS: entry=X, stop=Y, target=Z, portfolio=P, risk_pct=1%
CALCULATION:
  risk_amount = P * 0.01 = R
  stop_distance = entry - stop = D
  position_size = R / D = S units
  fee_entry = S * entry * 0.0026 = F1
  fee_exit = S * target * 0.0026 = F2
  gross_pnl = S * (target - entry) = G
  net_pnl = G - F1 - F2 = N
RESULT: [final numbers]
STATUS: READY_TO_LOG | HALT
```
