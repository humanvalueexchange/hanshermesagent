#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    clear_failure,
    load_config,
    load_manifest,
    normalize_whitespace,
    now_iso,
    parse_filename_metadata,
    record_failure,
    save_manifest,
    sha256_text,
    split_pdf_pages,
    guess_chapter,
)


def build_chunks(pages: list[str], chunk_size: int, overlap: int) -> list[dict]:
    units: list[dict] = []
    for page_number, page_text in enumerate(pages, start=1):
        paragraphs = [normalize_whitespace(part) for part in page_text.split("\n\n")]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        if not paragraphs:
            continue
        for paragraph in paragraphs:
            units.append({"page": page_number, "text": paragraph})

    chunks: list[dict] = []
    current_parts: list[dict] = []
    current_len = 0
    carry_text = ""

    for unit in units:
        unit_len = len(unit["text"])
        if current_parts and current_len + unit_len + 2 > chunk_size:
            chunk_text = "\n\n".join(item["text"] for item in current_parts).strip()
            chunks.append(
                {
                    "text": chunk_text,
                    "page_start": current_parts[0]["page"],
                    "page_end": current_parts[-1]["page"],
                }
            )
            carry_text = chunk_text[-overlap:].strip()
            current_parts = []
            current_len = 0

        if carry_text and not current_parts:
            current_parts.append({"page": unit["page"], "text": carry_text})
            current_len = len(carry_text)
            carry_text = ""

        current_parts.append(unit)
        current_len += unit_len + 2

    if current_parts:
        chunk_text = "\n\n".join(item["text"] for item in current_parts).strip()
        chunks.append(
            {
                "text": chunk_text,
                "page_start": current_parts[0]["page"],
                "page_end": current_parts[-1]["page"],
            }
        )

    return chunks


def process_manifest(root: Path, manifest_path: Path, chunk_size: int, overlap: int) -> tuple[int, str | None]:
    manifest = load_manifest(manifest_path)
    document_id = manifest["document_id"]

    if manifest.get("chunk_status") == "completed":
        return 0, None

    text_path_value = manifest.get("extracted_text_path")
    if not text_path_value:
        return 0, "missing extracted_text_path"

    text_path = Path(text_path_value)
    if not text_path.exists():
        return 0, "extracted text file missing"

    raw_text = text_path.read_text(encoding="utf-8", errors="ignore")
    pages = split_pdf_pages(raw_text)
    if not pages:
        return 0, "no extractable pages found"

    metadata = parse_filename_metadata(manifest["source_path"])
    chunk_records = []
    built_chunks = build_chunks(pages, chunk_size, overlap)
    for index, chunk in enumerate(built_chunks):
        source_page = pages[chunk["page_start"] - 1] if chunk["page_start"] - 1 < len(pages) else ""
        chunk_text = normalize_whitespace(chunk["text"])
        if not chunk_text:
            continue
        chunk_records.append(
            {
                "chunk_id": f"{document_id}-{index:05d}",
                "document_id": document_id,
                "source_path": manifest["source_path"],
                "sha256": manifest["sha256"],
                "book": metadata["book"],
                "author": metadata["author"],
                "chapter": guess_chapter(source_page),
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "chunk_index": index,
                "text": chunk_text,
                "embedding_model": "nomic-embed-text",
                "chunk_hash": sha256_text(chunk_text),
                "created_at": now_iso(),
                "publisher": metadata["publisher"],
                "publication_year": metadata["publication_year"],
            }
        )

    chunk_dir = root / "processed" / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunk_path = chunk_dir / f"{document_id}.jsonl"
    with chunk_path.open("w", encoding="utf-8") as handle:
        for record in chunk_records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    manifest["page_count"] = len(pages)
    manifest["author"] = metadata["author"]
    manifest["publisher"] = metadata["publisher"]
    manifest["publication_year"] = metadata["publication_year"]
    manifest["chunk_status"] = "completed"
    manifest["chunk_count"] = len(chunk_records)
    manifest["chunked_at"] = now_iso()
    manifest["chunk_path"] = str(chunk_path)
    manifest["pipeline_version"] = "phase2-chunking"
    save_manifest(manifest_path, manifest)
    clear_failure(root, document_id, "chunking")
    return len(chunk_records), None


def main() -> int:
    parser = argparse.ArgumentParser(description="Chunk extracted HVE library text.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    parser.add_argument("--limit", type=int, default=0, help="Optional manifest limit")
    args = parser.parse_args()

    config = load_config()
    chunk_size = int(config["retrieval"]["chunk_size_chars"])
    overlap = int(config["retrieval"]["chunk_overlap_chars"])
    root = Path(args.root)
    manifest_paths = sorted((root / "state" / "manifests").glob("*.json"))

    processed = 0
    total_chunks = 0
    for manifest_path in manifest_paths:
        chunk_count, error = process_manifest(root, manifest_path, chunk_size, overlap)
        document_id = manifest_path.stem
        if error:
            manifest = load_manifest(manifest_path)
            manifest["chunk_status"] = "failed"
            manifest["chunk_error"] = error
            save_manifest(manifest_path, manifest)
            record_failure(root, document_id, "chunking", error)
        else:
            processed += 1
            total_chunks += chunk_count
        if args.limit and processed >= args.limit:
            break

    print(f"PASS processed={processed} chunks={total_chunks} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
