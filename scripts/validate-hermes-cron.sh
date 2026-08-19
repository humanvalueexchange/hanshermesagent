#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="${HOME}/hermes-cfo"
HERMES_PY="${HOME}/.hermes/hermes-agent/venv/bin/python"
HERMES_ROOT="${HOME}/.hermes"
ACTIVE_PROFILE="$(cat "${HERMES_ROOT}/active_profile" 2>/dev/null || echo default)"

if [[ "${ACTIVE_PROFILE}" == "default" || -z "${ACTIVE_PROFILE}" ]]; then
  export HERMES_HOME="${HERMES_ROOT}"
else
  export HERMES_HOME="${HERMES_ROOT}/profiles/${ACTIVE_PROFILE}"
fi

"${HERMES_PY}" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))

from cron.jobs import list_jobs

expected = {
    "hermes-nightly-assessment": {"schedule": "0 2 * * *", "deliver": "local", "script": "nightly_assessment.py", "no_agent": True},
    "hermes-morning-briefing": {"schedule": "30 6 * * *", "deliver": "telegram", "script": "morning_briefing.py", "no_agent": True},
    "hermes-btc-forecast": {"schedule": "0 9 * * *", "deliver": "telegram", "script": "btc_forecast.py", "no_agent": True},
    "hermes-nightly-skill": {"schedule": "0 3 * * *", "deliver": "local", "script": None, "no_agent": False},
}

jobs = {job["name"]: job for job in list_jobs(include_disabled=True)}
errors = []

for name, spec in expected.items():
    job = jobs.get(name)
    if not job:
        errors.append(f"missing job: {name}")
        continue
    schedule = job.get("schedule", {})
    actual_schedule = schedule.get("expr") or schedule.get("display") or job.get("schedule_display")
    actual_deliver = job.get("deliver")
    actual_workdir = job.get("workdir")
    actual_script = job.get("script")
    actual_no_agent = job.get("no_agent")
    if actual_schedule != spec["schedule"]:
        errors.append(f"{name}: expected schedule {spec['schedule']}, got {actual_schedule}")
    if actual_deliver != spec["deliver"]:
        errors.append(f"{name}: expected deliver {spec['deliver']}, got {actual_deliver}")
    if spec["script"] is not None and actual_script != spec["script"]:
        errors.append(f"{name}: expected script {spec['script']}, got {actual_script}")
    if actual_no_agent != spec["no_agent"]:
        errors.append(f"{name}: expected no_agent {spec['no_agent']}, got {actual_no_agent}")
    if actual_workdir != str(Path.home() / "hermes-cfo"):
        errors.append(f"{name}: expected workdir {Path.home() / 'hermes-cfo'}, got {actual_workdir}")
    if not job.get("enabled", True):
        errors.append(f"{name}: job is disabled")

if errors:
    print("FAIL")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

print("PASS")
for name in expected:
    job = jobs[name]
    print(f"- {name}: next run {job.get('next_run_at')} (script={job.get('script')}, no_agent={job.get('no_agent')})")
PY
