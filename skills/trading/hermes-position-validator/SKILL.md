---
name: hermes-position-validator
description: "Validate every proposed Kraken BTC/USD trade before execution. Returns APPROVE or REJECT with SAT accounting and explicit failure reasons."
category: trading
version: 1.0
date: 2026-05-11
---

# hermes-position-validator — Position Sizing Cross-Validator

## Overview
Calls `src/tools/position_validator.py` to validate the proposed Kraken BTC/USD long before Hermes submits any order. The validator enforces risk, sizing, stop distance, long-only policy, SAT accounting, and the global halt flag.

## When to Invoke
- **Every proposed trade** before execution
- Before drawdown and sentiment checks are allowed to continue
- Paper or live — no exceptions

## Required Flow
1. Call the validator with the full proposed trade.
2. If `REJECT`: do not trade, call `audit_log.log_veto()`, and report the veto to Hans.
3. If `APPROVE`: proceed to drawdown check, then sentiment check, then submit the trade.

## Invocation
```bash
python3 ~/hermes-cfo/tools/position_validator.py \
  --side long \
  --entry 82000 \
  --stop 81180 \
  --target 83640 \
  --size-usd 100 \
  --account-equity 1000
```

JSON stdin is also supported:
```bash
echo '{"side":"long","entry":82000,"stop":81180,"target":83640,"size_usd":100,"account_equity":1000}' \
  | python3 ~/hermes-cfo/tools/position_validator.py
```

## Output Handling
- `APPROVE` + exit code `0` → continue to drawdown check
- `REJECT` + exit code `1` → veto the trade, log via `audit_log.log_veto()`, notify Hans
- `ERROR` + exit code `2` → malformed input, treat as operational failure and do not trade

## Realistic BTC Example
```bash
python3 ~/hermes-cfo/tools/position_validator.py \
  --side long \
  --entry 82000 \
  --stop 81180 \
  --target 83640 \
  --size-usd 100 \
  --account-equity 1000
```

Expected result: `APPROVE`, then continue to drawdown check, then sentiment check, then submit.
