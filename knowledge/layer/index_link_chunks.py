#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
from pathlib import Path

import lancedb
import pyarrow as pa

from build_lancedb_index import MODEL_NAME, TABLE_NAME
from common import iter_jsonl, now_iso
from ollama_embeddings import OllamaEmbedder


VECTOR_DIMENSION = 768


LIBRARY_CHUNKS_SCHEMA = pa.schema(
    [
        pa.field("chunk_id", pa.string()),
        pa.field("document_id", pa.string()),
        pa.field("source_path", pa.string()),
        pa.field("sha256", pa.string()),
        pa.field("book", pa.string()),
        pa.field("author", pa.string()),
        pa.field("chapter", pa.string()),
        pa.field("page_start", pa.int64()),
        pa.field("page_end", pa.int64()),
        pa.field("chunk_index", pa.int64()),
        pa.field("text", pa.string()),
        pa.field("embedding_model", pa.string()),
        pa.field("chunk_hash", pa.string()),
        pa.field("created_at", pa.string()),
        pa.field("publisher", pa.string()),
        pa.field("publication_year", pa.int64()),
        pa.field("vector", pa.list_(pa.float32(), VECTOR_DIMENSION)),
    ]
)


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


def index_chunks(root: Path, chunk_file: Path, manifest_path: Path) -> dict:
    records = list(iter_jsonl(chunk_file))
    if not records:
        return {"indexed": False, "status": "not_attempted", "error": "No chunk records"}

    document_id = str(records[0]["document_id"])
    if any(record.get("document_id") != document_id for record in records):
        return {"indexed": False, "status": "failed", "error": "Chunk document IDs do not match"}

    with index_lock(root):
        db = lancedb.connect(str(root / "index" / "lancedb"))
        if TABLE_NAME in db.list_tables().tables:
            table = db.open_table(TABLE_NAME)
            validate_index_compatibility(table)
            existing = (
                table.search()
                .where(f"document_id = '{document_id}'")
                .select(["source_path"])
                .limit(len(records))
                .to_arrow()
            )
            existing_source_paths = set(existing.column("source_path").to_pylist())
            record_source_path = str(records[0]["source_path"])
            if (
                table.count_rows(f"document_id = '{document_id}'") == len(records)
                and existing_source_paths == {record_source_path}
            ):
                return {
                    "indexed": True,
                    "status": "verified",
                    "table": TABLE_NAME,
                    "records": len(records),
                    "indexed_at": now_iso(),
                    "manifest_path": str(manifest_path),
                }
        else:
            table = None

        embedder = OllamaEmbedder(MODEL_NAME)
        vectors = embedder.encode([record["text"] for record in records], "search_document")
        for record, vector in zip(records, vectors):
            record["vector"] = vector
            record["embedding_model"] = MODEL_NAME

        if table is None:
            db.create_table(TABLE_NAME, data=records, schema=LIBRARY_CHUNKS_SCHEMA)
        else:
            (
                table.merge_insert("chunk_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .when_not_matched_by_source_delete(f"document_id = '{document_id}'")
                .execute(records)
            )
        verified = db.open_table(TABLE_NAME).count_rows(f"document_id = '{document_id}'")
        if verified != len(records):
            return {
                "indexed": False,
                "status": "failed",
                "error": f"Index verification found {verified} of {len(records)} records",
            }
        return {
            "indexed": True,
            "status": "indexed",
            "table": TABLE_NAME,
            "records": verified,
            "indexed_at": now_iso(),
            "manifest_path": str(manifest_path),
        }


def update_source_path(root: Path, document_id: str, source_path: str) -> int:
    with index_lock(root):
        db = lancedb.connect(str(root / "index" / "lancedb"))
        if TABLE_NAME not in db.list_tables().tables:
            return 0
        table = db.open_table(TABLE_NAME)
        count = table.count_rows(f"document_id = '{document_id}'")
        if count:
            table.update(
                where=f"document_id = '{document_id}'",
                values={"source_path": source_path},
            )
        return count


def validate_index_compatibility(table) -> None:
    """Fail clearly when an index was built with a different embedding contract."""
    schema = table.schema
    required_fields = {"embedding_model", "vector"}
    missing = required_fields - set(schema.names)
    if missing:
        raise RuntimeError(f"LanceDB index is missing required fields: {', '.join(sorted(missing))}")

    vector_type = schema.field("vector").type
    if not pa.types.is_fixed_size_list(vector_type) or vector_type.list_size != VECTOR_DIMENSION:
        raise RuntimeError(
            f"LanceDB vector dimension mismatch: expected {VECTOR_DIMENSION}, got {vector_type}"
        )

    sample = table.to_arrow().select(["embedding_model"]).slice(0, 1000)
    models = {value for value in sample.column("embedding_model").to_pylist() if value}
    if models and models != {MODEL_NAME}:
        raise RuntimeError(
            f"LanceDB embedding model mismatch: expected {MODEL_NAME}, found {', '.join(sorted(models))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Append or update one link document in LanceDB.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--chunk-file", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    try:
        result = index_chunks(Path(args.root), Path(args.chunk_file), Path(args.manifest))
    except Exception as exc:
        result = {"indexed": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))
    return 0 if result.get("indexed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
