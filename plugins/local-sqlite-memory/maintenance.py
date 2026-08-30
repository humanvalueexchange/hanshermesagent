#!/usr/bin/env python3
"""Bounded offline maintenance entry point for local-sqlite-memory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from store import LocalMemoryStore, MaintenanceLockError, resolve_db_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain local SQLite/FTS5 Hermes memory")
    parser.add_argument("--hermes-home", required=True, help="Active Hermes profile directory")
    parser.add_argument("--db-path", default="", help="Optional configured database path")
    parser.add_argument("--max-jobs", type=int, default=500, help="Maximum durable outbox jobs")
    parser.add_argument("--backup-keep", type=int, default=7, help="Number of SQLite snapshots to retain")
    parser.add_argument("--no-outbox", action="store_true", help="Skip durable outbox validation")
    parser.add_argument("--no-backup", action="store_true", help="Skip consistent SQLite backup")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Call and validate local extraction, then store reports without promotion (default)",
    )
    mode.add_argument(
        "--promote",
        action="store_true",
        help="Explicitly promote validated durable semantic facts into active memory",
    )
    parser.add_argument(
        "--rerun-reported",
        action="store_true",
        help="Re-run already dry-run-reported extract_turn jobs and append audit reports",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Explicitly retry failed extract_turn jobs that remain below the attempt limit",
    )
    parser.add_argument(
        "--extraction-model",
        default="qwen3.8-hermes:27b-128k",
        help="Approved local Ollama extraction model",
    )
    parser.add_argument(
        "--extraction-endpoint",
        default="http://127.0.0.1:11434/v1",
        help="Loopback OpenAI-compatible Ollama endpoint",
    )
    parser.add_argument(
        "--extraction-timeout",
        type=float,
        default=45.0,
        help="Per-job local model timeout in seconds (maximum 120)",
    )
    parser.add_argument(
        "--extraction-max-tokens",
        type=int,
        default=500,
        help="Maximum local model output tokens (maximum 1000)",
    )
    parser.add_argument(
        "--max-extraction-attempts",
        type=int,
        default=3,
        help="Maximum attempts for retryable local model failures (maximum 5)",
    )
    args = parser.parse_args()
    try:
        store = LocalMemoryStore(resolve_db_path(args.hermes_home, args.db_path))
        try:
            result = store.maintenance(
                process_outbox=not args.no_outbox,
                max_jobs=args.max_jobs,
                backup=not args.no_backup,
                backup_keep=args.backup_keep,
                dry_run=not args.promote,
                rerun_reported=args.rerun_reported or args.promote,
                retry_failed=args.retry_failed,
                extraction_model=args.extraction_model,
                extraction_endpoint=args.extraction_endpoint,
                extraction_timeout_seconds=args.extraction_timeout,
                extraction_max_tokens=args.extraction_max_tokens,
                max_attempts=args.max_extraction_attempts,
            )
        finally:
            store.close()
    except MaintenanceLockError as exc:
        print(str(exc), file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"local memory maintenance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
