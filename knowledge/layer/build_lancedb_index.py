#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
from pathlib import Path

import lancedb

from embedding_contract import CONTRACT_MODEL, REQUEST_MODEL

from common import iter_jsonl, load_manifest, now_iso, save_manifest
from ollama_embeddings import OllamaEmbedder


MODEL_NAME = CONTRACT_MODEL
TABLE_NAME = "library_chunks"


@contextlib.contextmanager
def index_lock(root: Path):
    lock_path = root / "state" / "lancedb-write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_chunk_records(root: Path) -> list[dict]:
    records: list[dict] = []
    for chunk_file in sorted((root / "processed" / "chunks").glob("*.jsonl")):
        records.extend(iter_jsonl(chunk_file))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LanceDB index for HVE library chunks.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    parser.add_argument("--limit", type=int, default=0, help="Optional chunk limit")
    args = parser.parse_args()

    root = Path(args.root)
    with index_lock(root):
        records = load_chunk_records(root)
        if args.limit:
            records = records[: args.limit]
        if not records:
            print(f"PASS records=0 root={root}")
            return 0

        embedder = OllamaEmbedder(REQUEST_MODEL)
        embeddings = embedder.encode([record["text"] for record in records], "search_document")
        for record, vector in zip(records, embeddings):
            record["vector"] = vector
            record["embedding_model"] = MODEL_NAME

        db = lancedb.connect(str(root / "index" / "lancedb"))
        db.create_table(TABLE_NAME, data=records, mode="overwrite")
        indexed_document_ids = {record["document_id"] for record in records}

    manifest_dir = root / "state" / "manifests"
    for manifest_path in sorted(manifest_dir.glob("*.json")):
        manifest = load_manifest(manifest_path)
        if manifest.get("document_id") not in indexed_document_ids:
            continue
        manifest["index_status"] = "completed"
        manifest["indexed_at"] = now_iso()
        manifest["index_table"] = TABLE_NAME
        save_manifest(manifest_path, manifest)

    print(f"PASS records={len(records)} table={TABLE_NAME} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
