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
    "twin-morning-brief-local-qwen": "10 6 * * *",
    "twin-health-watchdog-qwen38-honcho-embedding-hot": "every 30m",
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
    if name == "twin-morning-brief-local-qwen":
        if not job.get("no_agent"):
            errors.append(f"{name}: must remain no-agent deterministic execution")
        if job.get("script") != "hermes-morning-brief.py":
            errors.append(f"{name}: expected canonical script hermes-morning-brief.py")
        if job.get("model") != "qwen3.8-hermes:27b-128k":
            errors.append(f"{name}: expected qwen3.8-hermes:27b-128k model metadata")
        if job.get("provider") != "custom":
            errors.append(f"{name}: expected custom provider metadata")
        prompt = str(job.get("prompt", ""))
        if "qwen3.5" in prompt or "EST" in prompt:
            errors.append(f"{name}: stale model or timezone wording in contract")
        script_path = Path.home() / ".hermes" / "profiles" / Path(sys.argv[1]).parent.parent.name / "scripts" / "hermes-morning-brief.py"
        if not script_path.is_file():
            errors.append(f"{name}: missing active profile script {script_path}")

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
