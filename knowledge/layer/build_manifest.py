#!/usr/bin/env python3

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from common import load_manifest, save_manifest


MANIFEST_VERSION = "1.0"
PIPELINE_VERSION = "phase1-foundation"


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def discover_pdfs(root: Path) -> list[Path]:
    candidates = [
        root / "intake" / "test-batch",
        root / "intake" / "inbox",
        root / "raw" / "pdfs",
    ]
    pdfs: list[Path] = []
    for base in candidates:
        if not base.exists():
            continue
        pdfs.extend(sorted(path for path in base.rglob("*.pdf") if path.is_file()))
    return pdfs


def manifest_for(path: Path) -> dict:
    digest = sha256sum(path)
    return {
        "document_id": digest[:16],
        "source_path": str(path),
        "sha256": digest,
        "file_size_bytes": path.stat().st_size,
        "discovered_at": now_iso(),
        "ingest_status": "discovered",
        "title": path.stem,
        "author": None,
        "publisher": None,
        "publication_year": None,
        "language": None,
        "page_count": None,
        "extraction_status": "pending",
        "extraction_error": None,
        "extracted_text_path": None,
        "extraction_method": None,
        "ocr_status": "not_attempted",
        "ocr_language": "eng",
        "ocr_page_count": 0,
        "manifest_version": MANIFEST_VERSION,
        "pipeline_version": PIPELINE_VERSION,
    }


def write_manifests(root: Path, manifests: list[dict]) -> None:
    manifest_dir = root / "state" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for record in manifests:
        target = manifest_dir / f"{record['document_id']}.json"
        if target.exists():
            existing = load_manifest(target)
            merged = {**existing, **record}
            for key in (
                "extraction_status",
                "extraction_error",
                "extracted_text_path",
                "extracted_at",
                "chunk_status",
                "chunk_error",
                "chunk_count",
                "chunk_path",
                "chunked_at",
                "index_status",
                "indexed_at",
                "index_table",
                "page_count",
                "author",
                "publisher",
                "publication_year",
            ):
                if key in existing:
                    merged[key] = existing.get(key)
            save_manifest(target, merged)
        else:
            save_manifest(target, record)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HVE library manifests from PDFs.")
    parser.add_argument("--root", required=True, help="Knowledge-layer root path")
    args = parser.parse_args()

    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    pdfs = discover_pdfs(root)
    manifests = [manifest_for(path) for path in pdfs]
    write_manifests(root, manifests)
    print(f"PASS manifests={len(manifests)} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
