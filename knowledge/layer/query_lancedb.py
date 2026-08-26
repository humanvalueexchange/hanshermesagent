#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

import lancedb

from embedding_contract import REQUEST_MODEL

from ollama_embeddings import OllamaEmbedder
from index_link_chunks import validate_index_compatibility


TABLE_NAME = "library_chunks"


class QueryEmbedder:
    def __init__(self, _legacy_cache_dir: Path | None = None) -> None:
        self.embedder = OllamaEmbedder(REQUEST_MODEL)

    def encode(self, text: str) -> list[float]:
        return self.embedder.encode([text], "search_query")[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the HVE LanceDB sample index.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    parser.add_argument("--query", required=True, help="Semantic query")
    parser.add_argument("--top-k", type=int, default=5, help="Number of matches to return")
    args = parser.parse_args()

    root = Path(args.root)
    embedder = QueryEmbedder()
    db = lancedb.connect(str(root / "index" / "lancedb"))
    table = db.open_table(TABLE_NAME)
    try:
        validate_index_compatibility(table)
    except RuntimeError as exc:
        print(f"ERROR incompatible LanceDB index: {exc}")
        return 1
    results = table.search(embedder.encode(args.query)).limit(args.top_k).to_list()

    print(f"PASS query={args.query!r} matches={len(results)}")
    for row in results:
        print("---")
        print(f"book: {row.get('book')}")
        print(f"author: {row.get('author')}")
        print(f"chapter: {row.get('chapter')}")
        print(f"pages: {row.get('page_start')}-{row.get('page_end')}")
        print(f"source: {row.get('source_path')}")
        print(f"text: {row.get('text', '')[:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
