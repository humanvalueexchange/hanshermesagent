#!/usr/bin/env bash
set -euo pipefail

ACTIVE_PROFILE="$(cat "$HOME/.hermes/active_profile" 2>/dev/null || echo hanshermesagent)"
JOBS_FILE="$HOME/.hermes/profiles/$ACTIVE_PROFILE/cron/jobs.json"

[[ -f "$JOBS_FILE" ]] || {
  echo "FAIL"
  echo "- missing cron jobs file: $JOBS_FILE"
  exit 1
}

python3 - "$JOBS_FILE" <<'PY'
import json
import sys
from pathlib import Path

jobs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("jobs", [])
expected = {
    "twin-morning-brief-local-qwen-6am-EST": "10 6 * * *",
    "twin-health-watchdog-qwen-local-expected-hot": "every 30m",
    "hve-daily-skill-recommendation": "0 3 * * *",
    "hve-weekly-skill-review": "0 7 * * 1",
}
by_name = {job.get("name"): job for job in jobs}
errors = []
for name, schedule in expected.items():
    job = by_name.get(name)
    if not job:
        errors.append(f"missing job: {name}")
        continue
    actual = job.get("schedule_display") or (job.get("schedule") or {}).get("expr")
    if actual != schedule:
        errors.append(f"{name}: expected {schedule}, got {actual}")
    if not job.get("enabled"):
        errors.append(f"{name}: disabled")
    if not str(job.get("deliver", "")).startswith("whatsapp:"):
        errors.append(f"{name}: delivery is not WhatsApp")

if errors:
    print("FAIL")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

print("PASS")
for name in expected:
    job = by_name[name]
    print(f"- {name}: {job.get('schedule_display')} -> {job.get('deliver')}; next={job.get('next_run_at')}")
PY
