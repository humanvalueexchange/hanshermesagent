#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
from pathlib import Path

import lancedb
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from common import iter_jsonl, load_manifest, now_iso, save_manifest


MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
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


class Embedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        self.model = AutoModel.from_pretrained(
            model_name,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        ).to(self.device)
        self.model.eval()

    def encode(self, texts: list[str], prefix: str, batch_size: int = 16) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            prepared = [f"{prefix}: {text}" for text in batch]
            encoded = self.tokenizer(
                prepared,
                padding=True,
                truncation=True,
                max_length=1024,
                return_tensors="pt",
            ).to(self.device)
            with torch.no_grad():
                output = self.model(**encoded)
                hidden = output.last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1)
                summed = (hidden * mask).sum(dim=1)
                counts = mask.sum(dim=1).clamp(min=1)
                pooled = summed / counts
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.cpu().numpy().astype(np.float32).tolist())
            del encoded, output, hidden, mask, summed, counts, pooled
            if self.device == "cuda":
                torch.cuda.empty_cache()
        return vectors


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

        model_cache = root / "state" / "model-cache"
        embedder = Embedder(MODEL_NAME, model_cache)
        embeddings = embedder.encode([record["text"] for record in records], "search_document")
        for record, vector in zip(records, embeddings):
            record["vector"] = vector

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
