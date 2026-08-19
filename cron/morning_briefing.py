#!/usr/bin/env python3

from __future__ import annotations

from common import BRIEFINGS_DIR, build_btc_forecast, get_last_cron_output, today_str


def main() -> int:
    today = today_str()
    capability = BRIEFINGS_DIR / f"hermes-capability-assessment-{today}.md"
    trading = BRIEFINGS_DIR / f"hermes-algo-trading-status-{today}.md"
    cron = BRIEFINGS_DIR / f"hermes-cron-audit-{today}.md"
    missing = [path for path in (capability, trading, cron) if not path.exists() or path.stat().st_size == 0]

    if missing:
        print("FAIL")
        print("")
        print(f"🌅 HERMES EXECUTIVE MORNING BRIEFING — {today}")
        print("")
        print("1. Overnight accomplishments: FAIL — required briefing artifacts missing.")
        print("2. Current system state: Partial — trade-lane reports were not all generated.")
        print("3. Algorithmic trading status: FAIL — overnight artifact unavailable.")
        print("4. BTC forecast for 09:30 ET: FAIL — briefing artifact chain incomplete.")
        print("5. New skill learned last night: Out of scope for the mandatory trade lane.")
        print(f"6. Blockers / CTO flags: Missing files -> {', '.join(str(path) for path in missing)}")
        print("7. Next 3 actions today: rerun cron bootstrap; inspect Hermes cron output; verify local artifact generation.")
        return 1

    forecast = build_btc_forecast()
    print("PASS")
    print("")
    print(f"🌅 HERMES EXECUTIVE MORNING BRIEFING — {today}")
    print("")
    print("1. Overnight accomplishments")
    print(f"- PASS — capability assessment written: {capability.name}")
    print(f"- PASS — algorithmic trading status written: {trading.name}")
    print(f"- PASS — cron audit written: {cron.name}")
    print("")
    print("2. Current system state")
    print("- PASS — mandatory trade lane produced the required dated artifacts.")
    print("- PASS — knowledge-layer work remained out of scope.")
    print("")
    print("3. Algorithmic trading status")
    print("- PASS — overnight reporting lane completed.")
    print("- Trading posture remains paper-mode / validation-first until strategy trust is proven.")
    print("")
    print("4. BTC forecast for 09:30 ET")
    print(
        f"- PASS — current Kraken BTC/USD {forecast.current_price:.1f}; "
        f"predicted 09:30 ET {forecast.predicted_price:.1f}; "
        f"direction {forecast.direction}; confidence {forecast.confidence}."
    )
    print("")
    print("5. New skill learned last night")
    skill_output = get_last_cron_output("hermes-nightly-skill") or ""
    first_line = next((ln.strip() for ln in skill_output.splitlines() if ln.strip()), "")
    skill_detail = "unknown — no nightly-skill output found"
    if first_line.startswith("PASS"):
        skill_detail = first_line[4:].strip(" —-") or "skill created"
        print(f"- PASS — {skill_detail}")
    elif first_line.startswith("FAIL"):
        skill_detail = first_line[4:].strip(" —-") or "see cron output"
        print(f"- FAIL — {skill_detail}")
    else:
        print("- UNKNOWN — no nightly-skill output found")
    print("")
    print("6. Blockers / CTO flags")
    print("- PASS — no overnight artifact blockers detected in the mandatory lane.")
    print("")
    print("7. Next 3 actions today")
    print("- Review the three dated reports.")
    print("- Compare the 09:30 ET forecast against realized market behavior.")
    print("- Keep the knowledge lane deferred until the trade lane proves repeatable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
