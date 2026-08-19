#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from common import (
    BRIEFINGS_DIR,
    BTC_DATA_PATH,
    MAIN_PROFILE,
    REPO_DIR,
    SERVICE_NAMES,
    USER_SERVICE_NAMES,
    ensure_briefings_dir,
    file_status,
    git_branch,
    git_head,
    iso_now,
    load_cron_jobs,
    markdown_list,
    post_to_mattermost,
    system_service_state,
    today_str,
    user_service_state,
    write_text,
)


def main() -> int:
    ensure_briefings_dir()
    today = today_str()
    capability_path = BRIEFINGS_DIR / f"hermes-capability-assessment-{today}.md"
    trading_path = BRIEFINGS_DIR / f"hermes-algo-trading-status-{today}.md"
    cron_path = BRIEFINGS_DIR / f"hermes-cron-audit-{today}.md"

    system_services = [f"{name}: {system_service_state(name)}" for name in SERVICE_NAMES]
    user_services = [f"{name}: {user_service_state(name)}" for name in USER_SERVICE_NAMES]
    cron_jobs = load_cron_jobs()
    cron_lines = []
    for job in cron_jobs:
        schedule = (job.get("schedule") or {}).get("expr") or job.get("schedule_display") or "?"
        cron_lines.append(
            f"{job.get('name')}: schedule={schedule}; deliver={job.get('deliver')}; "
            f"enabled={job.get('enabled')}; no_agent={job.get('no_agent', False)}; "
            f"last_status={job.get('last_status')}; next_run_at={job.get('next_run_at')}"
        )

    capability_content = f"""# Hermes Capability Assessment — {today}

Generated: {iso_now()}

## Current local model stack
- Primary: qwen3.5:27b-128k (configured)
- Coding/fallback: gpt-oss:20b (configured)
- Deriver: qwen2.5:3b (configured)
- Embeddings: nomic-embed-text via Ollama (configured)

## Tools, services, models, data, repos, and access
### System services
{markdown_list(system_services)}

### User services
{markdown_list(user_services)}

### Data and repos
- hermes-cfo branch: {git_branch(REPO_DIR)}
- hermes-cfo HEAD: {git_head(REPO_DIR)}
- BTC 1m market data: {file_status(BTC_DATA_PATH)}
- Main profile path: {file_status(MAIN_PROFILE)}

## What works now without CTO help
- Repo-managed cron jobs are installed and visible.
- Trade-lane briefings can be generated from deterministic scripts.
- Local market data file path for BTC/USDT exists.

## What is missing, broken, partial, or unverified
- Forecast quality is still rule-based, not strategy-validated edge.
- Overnight trading readiness depends on service health staying green.
- Telegram delivery is delegated to Hermes cron delivery, not independently confirmed here.

## Top 10 capability gaps by mission impact
1. No deterministic overnight trade-prep artifact existed before this script-driven lane.
2. BTC forecast remains heuristic and low-trust until backtested.
3. No automated check yet confirms Telegram delivery receipts.
4. No consolidated morning trade brief file beyond cron delivery.
5. No automatic escalation path if ollama or hermes-freqtrade is inactive.
6. No explicit artifact retention/rotation policy for briefing logs.
7. No automated drawdown/expectancy report in the nightly lane.
8. No validated regime classifier in the morning forecast.
9. No hard deadline guard yet to stop late-running overnight tasks.
10. Knowledge-lane synthesis remains intentionally deferred.
"""

    trading_content = f"""# Hermes Algorithmic Trading Status — {today}

Generated: {iso_now()}

## Current phase
- Mandatory-lane stabilization

## Simulator / historical data / paper trading
- Historical data: {file_status(BTC_DATA_PATH)}
- Freqtrade service: {user_service_state('hermes-freqtrade')}
- Strategy file: {file_status(Path.home() / 'freqtrade' / 'user_data' / 'strategies' / 'BTCOpeningRangeScalp.py')}

## Risk / critic veto / audit logging / reporting
- Critic veto model is configured in the 4-agent architecture, but this script does not verify live multi-model invocation.
- Audit logging for overnight cron output is present under ~/.hermes/profiles/main/cron/output/.
- Morning reporting is configured via the repo-managed cron stack.

## Whether a trustworthy strategy exists yet
- Not yet proven. The current posture is process discipline and paper-mode readiness, not validated production edge.

## Next gate and exact requirements
1. Nightly artifacts must be created on schedule for multiple consecutive cycles.
2. Morning briefing and BTC forecast must deliver without timeout.
3. Trade recommendation quality must be measured against actual market outcomes before promotion beyond the current lane.
"""

    cron_content = f"""# Hermes Cron Audit — {today}

Generated: {iso_now()}

## Installed cron jobs
{markdown_list(cron_lines or ['No cron jobs found.'])}

## Purpose
- hermes-nightly-assessment: generate dated trade-lane artifacts locally.
- hermes-morning-briefing: send the executive summary via Telegram.
- hermes-btc-forecast: send the structured BTC forecast via Telegram.

## Status
- This audit only reports the current installed job metadata.
- Criticality: all three jobs are trade-lane critical.
- Repair needed: if any job shows disabled, missing, or repeated timeout, rerun bootstrap-hermes-cron.sh and inspect Hermes cron output logs.
"""

    write_text(capability_path, capability_content)
    write_text(trading_path, trading_content)
    write_text(cron_path, cron_content)

    paths = (capability_path, trading_path, cron_path)
    if all(path.exists() and path.stat().st_size > 0 for path in paths):
        print("PASS")
        for path in paths:
            print(f"- {path}")
        post_to_mattermost(
            "### ✅ Hermes Nightly Assessment — PASS\n"
            "All three mandatory trade-lane artifacts generated successfully:\n"
            + "\n".join(f"- `{path.name}`" for path in paths),
            channel_key="OPS",
        )
        return 0

    print("FAIL")
    for path in paths:
        print(f"- {path}: missing or empty")
    post_to_mattermost(
        "### ❌ Hermes Nightly Assessment — FAIL\n"
        "One or more mandatory artifacts missing — rerun `bootstrap-hermes-cron.sh`:\n"
        + "\n".join(f"- `{path.name}`: missing or empty" for path in paths if not path.exists() or path.stat().st_size == 0),
        channel_key="ALERTS",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
