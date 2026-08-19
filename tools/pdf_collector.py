from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


KNOWLEDGE_ROOT = Path("/hve-library")
INBOX_ROOT = KNOWLEDGE_ROOT / "intake" / "inbox"
MANIFEST_ROOT = KNOWLEDGE_ROOT / "state" / "manifests"
ALLOWED_ATTACHMENT_ROOT = Path.home() / ".hermes" / "profiles" / "hanshermesagent" / "cache" / "documents"
PIPELINE_SCRIPT = Path("/home/hans/hermes-cfo/knowledge/layer/run_intake_pipeline.py")
PIPELINE_PYTHON = Path.home() / ".hve-knowledge" / "venv" / "bin" / "python3"
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_CONTEXT_LENGTH = 20_000


class PdfCollectorError(RuntimeError):
    pass


def _sanitize_context(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:MAX_CONTEXT_LENGTH] or None


def _safe_attachment_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise PdfCollectorError(f"Attachment is not readable: {exc}") from exc

    try:
        resolved.relative_to(ALLOWED_ATTACHMENT_ROOT.resolve())
    except ValueError as exc:
        raise PdfCollectorError("PDF must come from the Hans Hermes attachment cache") from exc

    if resolved.suffix.lower() != ".pdf":
        raise PdfCollectorError("Only PDF attachments are accepted")
    if resolved.stat().st_size > MAX_PDF_BYTES:
        raise PdfCollectorError("PDF exceeds the 30 MB intake limit")
    return resolved


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    stem = Path(cleaned or "document").stem
    return f"{stem[:176]}.pdf"


def _document_id(pdf_path: Path) -> str:
    digest = hashlib.sha256()
    with pdf_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def _record_capture(document_id: str, capture_context: str | None) -> dict[str, Any]:
    manifest_path = MANIFEST_ROOT / f"{document_id}.json"
    if not manifest_path.is_file():
        return {"status": "indexed", "document_id": document_id}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_type"] = "pdf_document"
    manifest["capture_source"] = "telegram_collector"
    captured_at = datetime.now(timezone.utc).isoformat()
    manifest["capture_context"] = capture_context
    manifest["captured_at"] = manifest.get("captured_at") or captured_at
    captures = manifest.get("captures")
    if not isinstance(captures, list):
        captures = []
    captures.append(
        {
            "captured_at": captured_at,
            "capture_context": capture_context,
            "capture_source": "telegram_collector",
        }
    )
    manifest["captures"] = captures
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "indexed" if manifest.get("status") == "indexed" else manifest.get("status", "processed"),
        "document_id": document_id,
        "title": manifest.get("title"),
        "source_path": manifest.get("source_path"),
        "indexed": manifest.get("status") == "indexed",
        "chunk_count": manifest.get("chunk_count", 0),
    }


def archive_pdf(
    pdf_path: str,
    capture_context: str | None = None,
    *,
    root: Path = KNOWLEDGE_ROOT,
) -> dict[str, Any]:
    source = _safe_attachment_path(pdf_path)
    context = _sanitize_context(capture_context)
    inbox = root / "intake" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    destination = inbox / _safe_filename(source.name)
    if destination.exists():
        destination = inbox / f"{source.stem}-{_document_id(source)}.pdf"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=inbox,
            prefix=f".{destination.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        shutil.copy2(source, temporary_path)
        temporary_path.replace(destination)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()

    command = [
        str(PIPELINE_PYTHON),
        str(PIPELINE_SCRIPT),
        "--root",
        str(root),
        "--pdf",
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    document_id = _document_id(source)
    if result.returncode != 0:
        return {
            "status": "failed",
            "archived": False,
            "indexed": False,
            "document_id": document_id,
            "error": error or output or "PDF intake pipeline failed",
        }

    record = _record_capture(document_id, context)
    record.update(
        {
            "archived": True,
            "indexed": record.get("indexed", False),
            "pipeline_output": output[-2000:],
        }
    )
    return record
