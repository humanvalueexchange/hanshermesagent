---
name: hermes-drawdown-monitor
description: "Run the Hermes drawdown monitor before every Kraken BTC/USD trade cycle to enforce daily, weekly, equity, and loss-streak circuit breakers."
category: trading
version: 1.0
date: 2026-05-11
---

# hermes-drawdown-monitor — Drawdown Guardrail

## When to Invoke
- **Before every trade cycle** — run `python3 ~/hermes-cfo/tools/drawdown_monitor.py check` before research, critic, or execution.
- Any time Hermes needs current equity, open BTC positions, or halt-state confirmation.
- During incident response if trading should already be stopped.

## How to Interpret Output
- `account_equity` is the monitored portfolio equity in USDT.
- `daily_pnl_pct` and `weekly_pnl_pct` are the active drawdown gauges.
- `consecutive_losses` is the current closed-trade loss streak.
- `circuit_breakers` lists each triggered breaker as `{name, reason}`.
- `halt_active=true` means the global halt flag already exists at `~/.hermes/halt`.

## Required Actions
1. Run:
   ```bash
   python3 ~/hermes-cfo/tools/drawdown_monitor.py check
   ```
2. If exit code is `0` and `halt_active` is `false`, continue the trade cycle.
3. If exit code is `1` or a soft-halt breaker fires:
   - Stop the trade cycle immediately.
   - Notify Hans via Telegram.
   - Do **not** place, modify, or queue new trades.
4. If exit code is `2` or a hard-halt breaker fires:
   - Stop all trading immediately.
   - Notify Hans via Telegram with the breaker reason.
   - Treat the platform as locked down until Hans clears the halt.
5. If `halt_active` is `true`:
   - Stop.
   - Notify Hans via Telegram that Hermes remains halted.
   - **Do not self-resume and do not remove `~/.hermes/halt`.**

## Breaker Semantics
- `CB-1`: Daily drawdown >= 2% → soft halt.
- `CB-2`: Weekly drawdown >= 5% → hard halt.
- `CB-3`: Single-trade loss >= 1.5% → alert only, no halt.
- `CB-4`: Equity below $800 → hard halt.
- `CB-5`: 3 consecutive losses → soft halt.

## Notes
- The monitor prefers the Freqtrade REST API and falls back to SQLite if the API is unavailable.
- Hermes must treat any non-zero exit code or active halt flag as a **no-trade condition**.
