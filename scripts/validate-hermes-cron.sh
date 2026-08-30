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
        if job.get("no_agent"):
            errors.append(f"{name}: must use agent-driven synthesis")
        if job.get("script") != "hermes-morning-brief.py":
            errors.append(f"{name}: expected canonical script hermes-morning-brief.py")
        if job.get("model") != "qwen3.8-hermes:27b-128k":
            errors.append(f"{name}: expected qwen3.8-hermes:27b-128k model metadata")
        if job.get("provider") != "custom":
            errors.append(f"{name}: expected custom provider metadata")
        if job.get("reasoning_effort") != "high":
            errors.append(f"{name}: expected high reasoning effort")
        if not {"web", "file"}.issubset(set(job.get("enabled_toolsets") or [])):
            errors.append(f"{name}: web and file toolsets are required")
        prompt = str(job.get("prompt", ""))
        prompt_lower = prompt.lower()
        for required in ("astro-weather seed", "exact urls", "exactly three", "9000 characters", "uncertainty", "local-only"):
            if required not in prompt_lower:
                errors.append(f"{name}: prompt missing {required} contract")
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

PROFILE_CONFIG="$HOME/.hermes/profiles/$ACTIVE_PROFILE/config.yaml"
EXPECTED_LINK_COLLECTOR="/home/hans/hanshermesagent/mcp/link_collector_server.py"
EXPECTED_LINK_LIBRARY="/home/hans/hanshermesagent/mcp/link_library_server.py"
EXPECTED_LIGHTPANDA_BINARY="/home/hans/.local/bin/lightpanda"
EXPECTED_LIGHTPANDA_PLUGIN="/home/hans/hanshermesagent/plugins/lightpanda"
GATEWAY_OVERRIDE="$HOME/.config/systemd/user/hermes-gateway-hanshermesagent.service.d/override.conf"

[[ -f "$PROFILE_CONFIG" ]] || {
  echo "FAIL"
  echo "- missing active profile config: $PROFILE_CONFIG"
  exit 1
}

for path in "$EXPECTED_LINK_COLLECTOR" "$EXPECTED_LINK_LIBRARY"; do
  [[ -f "$path" ]] || {
    echo "FAIL"
    echo "- missing configured MCP server: $path"
    exit 1
  }
  grep -Fq "command: $path" "$PROFILE_CONFIG" || {
    echo "FAIL"
    echo "- active profile does not configure MCP server: $path"
    exit 1
  }
done

if grep -Fq "/home/hans/hermes-cfo/mcp/link_" "$PROFILE_CONFIG"; then
  echo "FAIL"
  echo "- active profile contains stale hermes-cfo link MCP path"
  exit 1
fi

[[ -x "$EXPECTED_LIGHTPANDA_BINARY" ]] || {
  echo "FAIL"
  echo "- missing executable Lightpanda binary: $EXPECTED_LIGHTPANDA_BINARY"
  exit 1
}

[[ -f "$EXPECTED_LIGHTPANDA_PLUGIN/plugin.yaml" && -f "$EXPECTED_LIGHTPANDA_PLUGIN/provider.py" ]] || {
  echo "FAIL"
  echo "- incomplete Lightpanda plugin: $EXPECTED_LIGHTPANDA_PLUGIN"
  exit 1
}

grep -Fq "extract_backend: lightpanda" "$PROFILE_CONFIG" || {
  echo "FAIL"
  echo "- active profile does not select Lightpanda for web extraction"
  exit 1
}

grep -Fq "web-lightpanda" "$PROFILE_CONFIG" || {
  echo "FAIL"
  echo "- active profile does not enable the Lightpanda plugin"
  exit 1
}

grep -Fq "request_timeout_seconds: 300" "$PROFILE_CONFIG" || {
  echo "FAIL"
  echo "- active profile does not set the local provider request timeout to 300 seconds"
  exit 1
}

grep -Fq "stale_timeout_seconds: 300" "$PROFILE_CONFIG" || {
  echo "FAIL"
  echo "- active profile does not set the local provider stale timeout to 300 seconds"
  exit 1
}

grep -Fq 'Environment="HERMES_CRON_TIMEOUT=900"' "$GATEWAY_OVERRIDE" || {
  echo "FAIL"
  echo "- gateway Cron timeout must remain 900 seconds"
  exit 1
}

grep -Fq 'Environment="HERMES_API_CALL_STALE_TIMEOUT=300"' "$GATEWAY_OVERRIDE" || {
  echo "FAIL"
  echo "- gateway API stale timeout must be 300 seconds"
  exit 1
}
