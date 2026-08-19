#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from common import clear_failure, load_manifest, now_iso, save_manifest
from index_link_chunks import update_source_path


def _count_chunk_records(chunk_path: Path) -> int:
    if not chunk_path.exists():
        return 0
    return sum(1 for line in chunk_path.read_text(encoding="utf-8").splitlines() if line.strip())


def _unique_destination(raw_pdfs: Path, filename: str) -> Path:
    candidate = raw_pdfs / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while candidate.exists():
        candidate = raw_pdfs / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def finalize_pdf(root: Path, pdf_path: Path, manifest_path: Path | None = None) -> tuple[bool, str]:
    inbox_dir = root / "intake" / "inbox"
    processing_dir = root / "intake" / "processing"
    raw_pdfs = root / "raw" / "pdfs"
    raw_pdfs.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists() or (inbox_dir not in pdf_path.parents and processing_dir not in pdf_path.parents):
        return True, f"WARN finalize skipped path={pdf_path} not in inbox"

    if manifest_path is None:
        return False, f"missing manifest for {pdf_path.name}"

    manifest = load_manifest(manifest_path)
    chunk_count = manifest.get("chunk_count")
    if chunk_count is None:
        chunk_path_value = manifest.get("chunk_path")
        if not chunk_path_value:
            return False, f"missing chunk_count for {pdf_path.name}"
        chunk_count = _count_chunk_records(Path(chunk_path_value))
        if chunk_count == 0:
            return False, f"missing chunk records for {pdf_path.name}"

    destination = _unique_destination(raw_pdfs, pdf_path.name)
    pdf_path.replace(destination)

    manifest["source_path"] = str(destination)
    manifest["ingest_status"] = "ingested"
    manifest["status"] = "indexed"
    manifest["indexed_at"] = now_iso()
    manifest["chunk_count"] = chunk_count
    manifest["failed_stage"] = None
    manifest["failed_at"] = None
    manifest["failure_error"] = None
    save_manifest(manifest_path, manifest)
    document_id = manifest_path.stem
    updated_rows = update_source_path(root, document_id, str(destination))
    if updated_rows == 0:
        return False, f"LanceDB provenance update found no rows for {document_id}"
    clear_failure(root, document_id, "indexing")
    clear_failure(root, document_id, "finalize")

    relative_path = destination.relative_to(root)
    title = manifest.get("title", destination.stem)
    return True, f"FINALIZED title={title} chunks={chunk_count} path={relative_path}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize indexed PDFs into the raw archive.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    parser.add_argument("--pdf", required=True, help="PDF path to finalize")
    args = parser.parse_args()

    root = Path(args.root)
    pdf_path = Path(args.pdf)
    manifest_dir = root / "state" / "manifests"
    manifest_path = None
    for candidate in manifest_dir.glob("*.json"):
        manifest = load_manifest(candidate)
        if manifest.get("source_path") == str(pdf_path):
            manifest_path = candidate
            break

    ok, message = finalize_pdf(root, pdf_path, manifest_path)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
