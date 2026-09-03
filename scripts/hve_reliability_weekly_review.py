#!/usr/bin/env python3
"""Read-only weekly reliability aggregation with durable review decisions."""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from hve_reliability_store import ReliabilityStore, ReliabilityStoreError, default_db_path


TORONTO = ZoneInfo("America/Toronto")


def previous_period(today: date | None = None) -> tuple[str, str]:
    local_today = today or datetime.now(TORONTO).date()
    this_monday = local_today - timedelta(days=local_today.weekday())
    start = datetime.combine(this_monday - timedelta(days=7), time.min, TORONTO)
    end = datetime.combine(this_monday, time.min, TORONTO)
    return start.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds"), end.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=default_db_path())
    parser.add_argument("--period-start", default="")
    parser.add_argument("--period-end", default="")
    parser.add_argument("--reviewer", default=os.environ.get("HVE_RELIABILITY_REVIEWER", "hermes-no-agent"))
    args = parser.parse_args()
    period_start, period_end = previous_period()
    if args.period_start:
        period_start = args.period_start
    if args.period_end:
        period_end = args.period_end
    try:
        with ReliabilityStore(args.db_path) as store:
            result = store.review(period_start, period_end, reviewer=args.reviewer)
    except ReliabilityStoreError as exc:
        print(f"HVE reliability review failure: {exc}")
        return 1

    material = [
        item for item in result["decisions"]
        if item["decision"] in {"escalate", "investigate"}
    ]
    if not material:
        return 0
    print(f"HVE reliability weekly review — {period_start[:10]} to {period_end[:10]}")
    print(f"Decisions recorded: {len(result['decisions'])}")
    for item in material[:12]:
        print(
            f"• {item['decision'].upper()} {item['severity'].upper()} "
            f"{item['event_type']} ({item['profile']}/{item['subsystem']}) "
            f"occurrences={item['occurrence_count']}: {item['rationale']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
