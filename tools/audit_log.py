#!/usr/bin/env python3
"""
Hermes Trade Audit Logger.
Immutable append-only JSON audit trail for local trade decisions.
"""
import json
import sys
import os
from datetime import datetime, timezone

LOG_DIR = os.path.expanduser("~/hermes-cfo/logs/trades")

def write_entry(entry: dict):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, f"{today}.json")
    entry["logged_at_utc"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Audit log entry written: {path}")

def log_trade_cycle(symbol, direction, entry_price, stop, target, size_btc,
                    risk_pct, research_summary, critic_decision, critic_reason,
                    execution_math, mode="paper", circuit_breaker_events=None):
    entry = {
        "type": "TRADE_CYCLE",
        "mode": mode,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "size_btc": size_btc,
        "size_sats": int(size_btc * 1e8),
        "risk_pct": risk_pct,
        "research_summary": research_summary,
        "critic_decision": critic_decision,
        "critic_reason": critic_reason,
        "execution_math": execution_math,
        "circuit_breaker_events": circuit_breaker_events or [],
        "agents": {
            "primary": "qwen3.8:27b",
            "coding": "qwen3.8:27b",
            "deriver": "qwen2.5:3b"
        }
    }
    write_entry(entry)

def log_veto(symbol, reason, consecutive_veto_count):
    write_entry({
        "type": "CONDUCTOR_VETO",
        "symbol": symbol,
        "veto_reason": reason,
        "consecutive_veto_count": consecutive_veto_count,
        "primary_model": "qwen3.8:27b"
    })

def log_circuit_breaker(trigger, value=None, action=None):
    """Support both legacy (trigger, value, action) and newer (trigger, reason) calls."""
    if action is None:
        action = value
        value = None
    write_entry({
        "type": "CIRCUIT_BREAKER",
        "trigger": trigger,
        "value": value,
        "action": action
    })

def log_halt(reason, source="cto_system"):
    """source: hermes_self | hans_telegram | cto_system"""
    write_entry({
        "type": "HALT",
        "reason": reason,
        "source": source,
        "halt_flag_path": os.path.expanduser("~/.hermes/halt")
    })
    halt_path = os.path.expanduser("~/.hermes/halt")
    os.makedirs(os.path.dirname(halt_path), exist_ok=True)
    with open(halt_path, "w") as f:
        f.write(f"{reason} | {datetime.now(timezone.utc).isoformat()} | source: {source}\n")
    print(f"Halt flag written: {halt_path}")

def check_halt():
    """Returns True if halt flag exists. Always call before a trade cycle."""
    return os.path.exists(os.path.expanduser("~/.hermes/halt"))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check_halt":
        if check_halt():
            print("HALT FLAG ACTIVE — do not trade")
            sys.exit(1)
        else:
            print("No halt flag — clear to trade")
            sys.exit(0)
    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        log_circuit_breaker("TEST", 0.0, "Testing audit log system")
        print("Test entry written successfully.")
