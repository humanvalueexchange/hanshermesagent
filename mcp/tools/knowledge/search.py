#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.disable(logging.WARNING)

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.knowledge_layer_client import KNOWLEDGE_ROOT as CLIENT_ROOT, run_cli  # noqa: E402

KNOWLEDGE_ROOT = CLIENT_ROOT
LANCEDB_DIR = KNOWLEDGE_ROOT / "index" / "lancedb"


def _format_pages(page_start: object, page_end: object) -> str:
    if page_start in (None, "") and page_end in (None, ""):
        return "unknown"
    if page_start == page_end:
        return str(page_start)
    start = page_start if page_start not in (None, "") else "?"
    end = page_end if page_end not in (None, "") else "?"
    return f"{start}-{end}"


def _excerpt(value: object) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= 400:
        return text
    return f"{text[:397].rstrip()}..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic search over the HVE LanceDB library index.")
    parser.add_argument("--query", required=True, help="Semantic query string")
    parser.add_argument("--max-results", type=int, default=5, help="Maximum matches to return")
    args = parser.parse_args()

    if not LANCEDB_DIR.exists():
        print(f"LanceDB directory not found at {LANCEDB_DIR}", file=sys.stderr)
        return 1

    completed = run_cli(["query", args.query, "--top-k", str(max(1, args.max_results))])
    if completed.returncode != 0:
        print((completed.stderr or completed.stdout).strip(), file=sys.stderr)
        return completed.returncode
    rows = json.loads(completed.stdout)

    payload = []
    for row in rows:
        distance = row.get("_distance")
        score = None
        if distance is not None:
            score = round(max(0.0, 1 - float(distance)), 4)
        payload.append(
            {
                "book": row.get("book"),
                "author": row.get("author"),
                "chapter": row.get("chapter"),
                "pages": _format_pages(row.get("page_start"), row.get("page_end")),
                "score": score,
                "excerpt": _excerpt(row.get("text")),
            }
        )

    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
