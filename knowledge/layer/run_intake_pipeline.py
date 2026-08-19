#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Iterator

import yaml

from build_manifest import manifest_for
from chunk_text import process_manifest
from common import clear_failure, load_manifest, now_iso, record_failure, save_manifest
from extract_pdf_text import extract_text_with_metadata
from finalize import finalize_pdf
from index_link_chunks import restore_document, snapshot_document


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "knowledge-layer" / "knowledge-layer.yaml"
INDEX_SCRIPT = Path(__file__).with_name("index_link_chunks.py")
VENV_PYTHON = Path.home() / ".hve-knowledge" / "venv" / "bin" / "python3"
LOCK_PATH = "state/intake.lock"

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
Emit = Callable[[str], None]


def load_pipeline_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def discover_inbox_pdfs(root: Path, specific_pdf: Path | None = None) -> list[Path]:
    inbox_dir = root / "intake" / "inbox"
    processing_dir = root / "intake" / "processing"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    processing_dir.mkdir(parents=True, exist_ok=True)
    if specific_pdf:
        return [specific_pdf] if specific_pdf.exists() else []
    pending = [
        path
        for directory in (inbox_dir, processing_dir)
        for path in directory.glob("*.pdf")
        if path.is_file()
    ]
    return sorted(pending)


def claim_pdf(root: Path, pdf_path: Path) -> Path | None:
    """Atomically transfer ownership of an inbox PDF to this worker."""
    processing_dir = root / "intake" / "processing"
    processing_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(processing_dir, pdf_path.name)
    try:
        pdf_path.replace(destination)
    except FileNotFoundError:
        return None
    return destination


@contextlib.contextmanager
def intake_lock(root: Path) -> Iterator[bool]:
    lock_path = root / LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def _merge_manifest(existing: dict, record: dict) -> dict:
    merged = {**existing, **record}
    for key in (
        "extraction_status",
        "extraction_error",
        "extracted_text_path",
        "extracted_at",
        "extraction_method",
        "ocr_status",
        "ocr_language",
        "ocr_page_count",
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
        "language",
        "status",
        "failed_at",
        "failed_stage",
        "failure_error",
    ):
        if key in existing:
            merged[key] = existing.get(key)
    return merged


def ensure_manifest(root: Path, pdf_path: Path) -> tuple[Path, dict, bool]:
    manifest_dir = root / "state" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    record = manifest_for(pdf_path)
    manifest_path = manifest_dir / f"{record['document_id']}.json"

    if not manifest_path.exists():
        save_manifest(manifest_path, record)
        return manifest_path, record, False

    existing = load_manifest(manifest_path)
    existing_source = Path(existing.get("source_path", ""))
    if (
        existing.get("status") == "indexed"
        and existing_source != pdf_path
        and existing_source.exists()
        and (root / "raw" / "pdfs") in existing_source.parents
    ):
        return manifest_path, existing, True

    merged = _merge_manifest(existing, record)
    merged["source_path"] = str(pdf_path)
    save_manifest(manifest_path, merged)
    return manifest_path, merged, False


def extract_manifest(root: Path, manifest_path: Path, pdf_path: Path) -> tuple[bool, str | None]:
    manifest = load_manifest(manifest_path)
    text_path = root / "processed" / "text" / f"{manifest['document_id']}.txt"

    if manifest.get("extraction_status") == "completed" and text_path.exists():
        return True, None

    ok, error, extraction_metadata = extract_text_with_metadata(pdf_path, text_path)
    manifest["source_path"] = str(pdf_path)
    manifest.update(extraction_metadata)
    if ok:
        manifest["extraction_status"] = "completed"
        manifest["ingest_status"] = "extracted"
        manifest["extracted_text_path"] = str(text_path)
        manifest["extracted_at"] = now_iso()
        manifest["extraction_error"] = None
        clear_failure(root, manifest["document_id"], "extraction")
    else:
        manifest["extraction_status"] = "failed"
        manifest["extraction_error"] = error
    save_manifest(manifest_path, manifest)
    return ok, error


def batch_chunk_files(manifest_paths: list[Path]) -> list[Path]:
    chunk_files: list[Path] = []
    for manifest_path in manifest_paths:
        manifest = load_manifest(manifest_path)
        chunk_path_value = manifest.get("chunk_path")
        if not chunk_path_value:
            raise ValueError(f"missing chunk_path for {manifest_path.stem}")
        chunk_path = Path(chunk_path_value)
        if not chunk_path.exists():
            raise ValueError(f"chunk file missing for {manifest_path.stem}: {chunk_path}")
        chunk_files.append(chunk_path)
    return chunk_files


def run_index_build(
    root: Path,
    runner: RunCommand,
    documents: list[tuple[Path, Path]],
) -> tuple[bool, str]:
    indexed_records = 0
    for chunk_file, manifest_path in documents:
        command = [
            str(VENV_PYTHON),
            str(INDEX_SCRIPT),
            "--root",
            str(root),
            "--chunk-file",
            str(chunk_file),
            "--manifest",
            str(manifest_path),
        ]
        result = runner(command, capture_output=True, text=True, check=False)
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            return False, stderr or stdout or "index build failed"
        try:
            indexed_records += int(json.loads(stdout).get("records", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False, f"indexer returned invalid output for {manifest_path.stem}"
    return True, f"PASS indexed_documents={len(documents)} records={indexed_records}"


def _unique_destination(base_dir: Path, filename: str) -> Path:
    candidate = base_dir / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while candidate.exists():
        candidate = base_dir / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def quarantine_pdf(
    root: Path,
    pdf_path: Path,
    manifest_path: Path | None,
    stage: str,
    error: str,
    *,
    mark_failure: bool = True,
) -> Path:
    failed_dir = root / "intake" / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(failed_dir, pdf_path.name)
    if pdf_path.exists():
        pdf_path.replace(destination)

    if mark_failure and manifest_path and manifest_path.exists():
        manifest = load_manifest(manifest_path)
        manifest["source_path"] = str(destination)
        manifest["ingest_status"] = "failed"
        manifest["status"] = "failed"
        manifest["failed_stage"] = stage
        manifest["failed_at"] = now_iso()
        manifest["failure_error"] = error
        save_manifest(manifest_path, manifest)
        record_failure(root, manifest["document_id"], stage, error)

    return destination


def _write_batch_journal(path: Path, journal: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    temporary.write_text(json.dumps(journal, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _new_batch_journal(root: Path, pending: list[tuple[Path, Path, float]]) -> tuple[Path, dict]:
    batch_id = f"{now_iso().replace(':', '').replace('+00:00', 'Z')}-{uuid.uuid4().hex[:8]}"
    journal = {
        "version": 1,
        "batch_id": batch_id,
        "status": "active",
        "created_at": now_iso(),
        "documents": [
            {
                "document_id": manifest_path.stem,
                "pdf_path": str(pdf_path),
                "manifest_path": str(manifest_path),
                "manifest_before": load_manifest(manifest_path),
                "previous_rows": None,
                "indexed": False,
            }
            for pdf_path, manifest_path, _ in pending
        ],
    }
    path = root / "state" / "intake-batches" / f"{batch_id}.json"
    _write_batch_journal(path, journal)
    return path, journal


def _rollback_batch(root: Path, journal_path: Path, journal: dict, reason: str) -> None:
    for entry in reversed(journal["documents"]):
        original_pdf = Path(entry["pdf_path"])
        manifest_path = Path(entry["manifest_path"])
        current_manifest = load_manifest(manifest_path)
        current_source = Path(str(current_manifest.get("source_path", original_pdf)))
        if current_source != original_pdf and current_source.exists():
            original_pdf.parent.mkdir(parents=True, exist_ok=True)
            if not original_pdf.exists():
                current_source.replace(original_pdf)
        rows = entry["previous_rows"]
        if rows is None:
            rows = []
        restore_document(root, entry["document_id"], rows)
        save_manifest(manifest_path, entry["manifest_before"])
    journal["status"] = "rolled_back"
    journal["rolled_back_at"] = now_iso()
    journal["rollback_reason"] = reason
    _write_batch_journal(journal_path, journal)


def recover_incomplete_batches(root: Path, emit: Emit = print) -> None:
    batch_dir = root / "state" / "intake-batches"
    if not batch_dir.exists():
        return
    for journal_path in sorted(batch_dir.glob("*.json")):
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("status") not in {"active", "indexed"}:
            continue
        reason = f"recovered interrupted batch {journal.get('batch_id', journal_path.stem)}"
        _rollback_batch(root, journal_path, journal, reason)
        emit(f"ROLLED_BACK batch={journal.get('batch_id', journal_path.stem)} reason={reason}")


def run_pipeline(
    root: Path,
    *,
    pdf_path: Path | None = None,
    dry_run: bool = False,
    runner: RunCommand = subprocess.run,
    extractor: Callable[[Path, Path, Path], tuple[bool, str | None]] = extract_manifest,
    chunker: Callable[[Path, Path, int, int], tuple[int, str | None]] = process_manifest,
    finalizer: Callable[[Path, Path, Path | None], tuple[bool, str]] = finalize_pdf,
    emit: Emit = print,
    timer: Callable[[], float] = time.monotonic,
) -> int:
    config = load_pipeline_config()
    chunk_size = int(config["retrieval"]["chunk_size_chars"])
    overlap = int(config["retrieval"]["chunk_overlap_chars"])
    recover_incomplete_batches(root, emit)
    pdfs = discover_inbox_pdfs(root, pdf_path)

    if not pdfs:
        emit(f"PASS indexed=0 failures=0 skipped=0 root={root}")
        return 0

    batch_start = timer()
    failed = 0
    skipped = 0
    pending_finalize: list[tuple[Path, Path, float]] = []

    for current_pdf in pdfs:
        if dry_run:
            if not current_pdf.exists():
                emit(f"SKIPPED title={current_pdf.stem} reason=file disappeared before processing")
                skipped += 1
                continue
        elif current_pdf.parent == root / "intake" / "processing":
            pass
        else:
            claimed_pdf = claim_pdf(root, current_pdf)
            if claimed_pdf is None:
                emit(f"SKIPPED title={current_pdf.stem} reason=file disappeared before claim")
                skipped += 1
                continue
            current_pdf = claimed_pdf
        title = current_pdf.stem
        started = timer()
        emit(f"[STEP 1/6] manifest title={title}")
        manifest_path, manifest, duplicate = ensure_manifest(root, current_pdf)
        title = manifest.get("title", title)

        if duplicate:
            destination = quarantine_pdf(
                root,
                current_pdf,
                None,
                "duplicate",
                "already indexed",
                mark_failure=False,
            )
            emit(f"SKIPPED title={title} reason=already indexed path={destination.relative_to(root)}")
            skipped += 1
            continue

        if dry_run:
            emit(f"[STEP 2/6] extract title={title} dry-run")
            emit(f"[STEP 3/6] chunk title={title} dry-run")
            emit(f"[STEP 4/6] index title={title} dry-run")
            emit(f"[STEP 5/6] finalize title={title} dry-run")
            emit(f"[STEP 6/6] indexed title={title} dry-run")
            continue

        emit(f"[STEP 2/6] extract title={title}")
        extracted, extract_error = extractor(root, manifest_path, current_pdf)
        if not extracted:
            destination = quarantine_pdf(root, current_pdf, manifest_path, "extraction", extract_error or "extract failed")
            emit(f"FAILED title={title} step=extraction error={extract_error or 'extract failed'} path={destination.relative_to(root)}")
            failed += 1
            continue

        emit(f"[STEP 3/6] chunk title={title}")
        chunk_count, chunk_error = chunker(root, manifest_path, chunk_size, overlap)
        if chunk_error:
            destination = quarantine_pdf(root, current_pdf, manifest_path, "chunking", chunk_error)
            emit(f"FAILED title={title} step=chunking error={chunk_error} path={destination.relative_to(root)}")
            failed += 1
            continue

        pending_finalize.append((current_pdf, manifest_path, started))
        emit(f"[STEP 4/6] index queued title={title} chunks={chunk_count}")

    if dry_run:
        emit(f"PASS dry_run=1 queued={len(pending_finalize)} failures=0 skipped={skipped} root={root}")
        return 0

    if pending_finalize:
        journal_path, journal = _new_batch_journal(root, pending_finalize)
        indexed_pending: list[tuple[Path, Path, float]] = []
        index_failure: tuple[Path, Path, str] | None = None
        snapshot_error: str | None = None
        for entry in journal["documents"]:
            try:
                entry["previous_rows"] = snapshot_document(root, entry["document_id"])
            except (OSError, RuntimeError, ValueError) as error:
                snapshot_error = str(error)
                break
        if snapshot_error:
            journal["status"] = "snapshot_failed"
            journal["snapshot_failed_at"] = now_iso()
            journal["snapshot_error"] = snapshot_error
            _write_batch_journal(journal_path, journal)
            emit(f"FAILED step=rollback_snapshot error={snapshot_error}")
            failed += 1
            pending_finalize = []
        else:
            _write_batch_journal(journal_path, journal)

        if not snapshot_error:
            for index, (current_pdf, manifest_path, started) in enumerate(pending_finalize):
                title = load_manifest(manifest_path).get("title", current_pdf.stem)
                emit(f"[STEP 4/6] build_lancedb_index title={title}")
                try:
                    documents = [
                        (chunk_file, manifest_path)
                        for chunk_file in batch_chunk_files([manifest_path])
                    ]
                    indexed, index_message = run_index_build(root, runner, documents)
                except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                    indexed = False
                    index_message = str(error)
                emit(index_message)
                if not indexed:
                    index_failure = (current_pdf, manifest_path, index_message)
                    break
                journal["documents"][index]["indexed"] = True
                _write_batch_journal(journal_path, journal)
                indexed_pending.append((current_pdf, manifest_path, started))
        if index_failure:
            failure_pdf, failure_manifest, failure_message = index_failure
            _rollback_batch(root, journal_path, journal, failure_message)
            destination = quarantine_pdf(root, failure_pdf, failure_manifest, "indexing", failure_message)
            emit(
                f"FAILED title={load_manifest(failure_manifest).get('title', failure_pdf.stem)} "
                f"step=indexing error={failure_message} path={destination.relative_to(root)}"
            )
            emit(f"ROLLED_BACK batch={journal['batch_id']} reason={failure_message}")
            failed += 1
            pending_finalize = []
        elif not snapshot_error:
            journal["status"] = "indexed"
            journal["indexed_at"] = now_iso()
            _write_batch_journal(journal_path, journal)
            pending_finalize = indexed_pending

    batch_failure = False
    for current_pdf, manifest_path, started in pending_finalize:
        title = load_manifest(manifest_path).get("title", current_pdf.stem)
        emit(f"[STEP 5/6] finalize title={title}")
        finalized, finalize_message = finalizer(root, current_pdf, manifest_path)
        emit(finalize_message)
        if not finalized:
            if pending_finalize:
                _rollback_batch(root, journal_path, journal, finalize_message)
            destination = quarantine_pdf(root, current_pdf, manifest_path, "finalize", finalize_message)
            emit(f"FAILED title={title} step=finalize error={finalize_message} path={destination.relative_to(root)}")
            failed += 1
            batch_failure = True
            break

        finalized_manifest = load_manifest(manifest_path)
        if pending_finalize:
            entry = next(item for item in journal["documents"] if item["document_id"] == manifest_path.stem)
            entry["finalized"] = True
            _write_batch_journal(journal_path, journal)
        elapsed = timer() - started
        emit(f"[STEP 6/6] indexed title={title}")
        emit(
            f"KNOWLEDGE_INDEXED document_id={manifest_path.stem} title={title} "
            f"chunks={finalized_manifest.get('chunk_count', 0)} "
            f"elapsed={elapsed:.2f}s source={finalized_manifest.get('source_path', '')}"
        )

    if pending_finalize and not batch_failure:
        journal["status"] = "committed"
        journal["committed_at"] = now_iso()
        _write_batch_journal(journal_path, journal)

    total_elapsed = timer() - batch_start
    emit(
        f"RESULT indexed={len(pending_finalize)} failures={failed} skipped={skipped} "
        f"elapsed={total_elapsed:.2f}s root={root}"
    )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the HVE intake pipeline for inbox PDFs.")
    parser.add_argument("--root", default="/hve-library", help="Knowledge-layer root path")
    parser.add_argument("--pdf", help="Optional specific PDF in intake/inbox to process")
    parser.add_argument("--dry-run", action="store_true", help="Print steps without mutating files")
    args = parser.parse_args()

    root = Path(args.root)
    pdf_path = Path(args.pdf) if args.pdf else None
    with intake_lock(root) as acquired:
        if not acquired:
            print("SKIPPED reason=another intake worker is active")
            return 0
        return run_pipeline(root, pdf_path=pdf_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
