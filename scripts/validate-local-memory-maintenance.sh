#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_ROOT="${HERMES_PROFILE_ROOT:-$HOME/.hermes/profiles/hanshermesagent}"
DB_PATH="$PROFILE_ROOT/local-memory.db"
PYTHON_BIN="${HERMES_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python}"
MAINTENANCE="$REPO_ROOT/plugins/local-sqlite-memory/maintenance.py"
OUTPUT_DIR="${HERMES_PREFLIGHT_OUTPUT_DIR:-$PROFILE_ROOT/workspace/ops-brief-logs}"
OUTPUT_PATH="$OUTPUT_DIR/local-memory-preflight-$(date -u +%Y%m%dT%H%M%SZ).json"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Hermes Python environment not found: $PYTHON_BIN" >&2
  exit 1
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "ERROR: local memory database not found: $DB_PATH" >&2
  exit 1
fi

read_state() {
  DB_PATH="$DB_PATH" "$PYTHON_BIN" - <<'PY'
import json
import os
import sqlite3

db_path = os.environ["DB_PATH"]
with sqlite3.connect(db_path) as db:
    db.execute("PRAGMA foreign_keys=ON")
    state = {
        "active_memories": db.execute(
            "SELECT COUNT(*) FROM memories WHERE status='active'"
        ).fetchone()[0],
        "fts_rows": db.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0],
        "vector_candidates": db.execute(
            "SELECT COUNT(*) FROM vector_candidates WHERE state != 'disabled'"
        ).fetchone()[0],
        "ledger_handoffs_pending": db.execute(
            "SELECT COUNT(*) FROM ledger_handoffs WHERE status='pending_confirmation'"
        ).fetchone()[0],
        "outbox": {
            row[0]: row[1]
            for row in db.execute(
                "SELECT status, COUNT(*) FROM outbox GROUP BY status"
            )
        },
        "extraction_reports": db.execute(
            "SELECT COUNT(*) FROM extraction_reports"
        ).fetchone()[0],
        "integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
        "foreign_key_errors": db.execute(
            "SELECT COUNT(*) FROM pragma_foreign_key_check"
        ).fetchone()[0],
    }
print(json.dumps(state, sort_keys=True))
PY
}

BEFORE="$(read_state)"
MAINTENANCE_OUTPUT="$(
  HERMES_HOME="$PROFILE_ROOT" \
  PYTHONPATH="$REPO_ROOT/plugins/local-sqlite-memory" \
  "$PYTHON_BIN" "$MAINTENANCE" \
    --hermes-home "$PROFILE_ROOT" \
    --dry-run \
    --max-jobs 1 \
    --no-backup
)"
AFTER="$(read_state)"

mkdir -p "$OUTPUT_DIR"
BEFORE="$BEFORE" AFTER="$AFTER" MAINTENANCE_OUTPUT="$MAINTENANCE_OUTPUT" \
  PROFILE_ROOT="$PROFILE_ROOT" OUTPUT_PATH="$OUTPUT_PATH" \
  "$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

before = json.loads(os.environ["BEFORE"])
after = json.loads(os.environ["AFTER"])
maintenance = json.loads(os.environ["MAINTENANCE_OUTPUT"].splitlines()[-1])

def active(unit):
    result = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "inactive"

timer = subprocess.run(
    ["systemctl", "--user", "show", "hermes-local-memory-maintenance.timer",
     "--property=NextElapseUSecRealtime", "--value"],
    capture_output=True,
    text=True,
    check=False,
).stdout.strip()

services = {
   "gateway": active("hermes-gateway-hanshermesagent.service"),
   "mcp": active("hermes-mcp.service"),
   "maintenance_timer": active("hermes-local-memory-maintenance.timer"),
}

report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "profile_root": os.environ["PROFILE_ROOT"],
    "mode": "dry_run",
    "services": services,
    "timer_next_run": timer,
    "before": before,
    "maintenance": maintenance,
    "after": after,
    "checks": {
        "integrity_ok": after["integrity_check"] == "ok",
        "foreign_keys_clean": after["foreign_key_errors"] == 0,
        "active_memory_unchanged": (
            before["active_memories"] == after["active_memories"]
        ),
        "fts_unchanged": before["fts_rows"] == after["fts_rows"],
        "vectors_disabled": after["vector_candidates"] == 0,
        "no_processing_jobs": after["outbox"].get("processing", 0) == 0,
        "services_active": all(report_status == "active" for report_status in services.values()),
    },
}
report["passed"] = all(report["checks"].values())
Path(os.environ["OUTPUT_PATH"]).write_text(
    json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
if not report["passed"]:
    raise SystemExit(1)
PY

echo "Preflight report: $OUTPUT_PATH" >&2
