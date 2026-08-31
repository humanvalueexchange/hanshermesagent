from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWLEDGE_ROOT = Path("/hve-library")
ANNOTATION_DIR = KNOWLEDGE_ROOT / "state" / "annotations"
MANIFEST_DIR = KNOWLEDGE_ROOT / "state" / "manifests"
DOCUMENT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_ANNOTATION_LENGTH = 20_000
MAX_EVIDENCE_LENGTH = 20_000
MAX_AUTHORITY_LENGTH = 200

ALLOWED_CLASSIFICATIONS = {
    "provenance",
    "correction",
    "context",
    "classification",
    "decision",
    "policy",
    "observation",
    "open_question",
}
ALLOWED_VERIFICATION_STATUSES = {
    "owner_attested",
    "source_verified",
    "independently_verified",
    "disputed",
    "unverified",
}
AUTHORIZED_AUTHORITIES = {"Hans Westphal"}


class AnnotationError(ValueError):
    pass


def _validate_document_id(document_id: str, root: Path) -> str:
    normalized = str(document_id or "").strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(normalized):
        raise AnnotationError("Expected a 16-character hexadecimal document ID.")
    if not (root / "state" / "manifests" / f"{normalized}.json").is_file():
        raise AnnotationError(f"Document {normalized} does not exist in the knowledge library.")
    return normalized


def _validate_text(value: str, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise AnnotationError(f"{field} must be a string.")
    cleaned = value.replace("\x00", "").strip()
    if not cleaned:
        raise AnnotationError(f"{field} must not be empty.")
    if len(cleaned) > limit:
        raise AnnotationError(f"{field} exceeds the {limit}-character limit.")
    return cleaned


def _annotation_path(document_id: str, root: Path) -> Path:
    return root / "state" / "annotations" / f"{document_id}.jsonl"


def read_annotations(document_id: str, *, root: Path = KNOWLEDGE_ROOT) -> list[dict[str, Any]]:
    normalized = str(document_id or "").strip().lower()
    if not DOCUMENT_ID_RE.fullmatch(normalized):
        return []
    path = _annotation_path(normalized, root)
    if not path.is_file():
        return []

    annotations: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                annotations.append(value)
    return annotations


def append_annotation(
    document_id: str,
    annotation: str,
    classification: str,
    verification_status: str,
    authority: str,
    evidence: str | None = None,
    *,
    root: Path = KNOWLEDGE_ROOT,
) -> dict[str, Any]:
    normalized_id = _validate_document_id(document_id, root)
    cleaned_annotation = _validate_text(annotation, "annotation", MAX_ANNOTATION_LENGTH)
    cleaned_classification = _validate_text(classification, "classification", 64).lower()
    if cleaned_classification not in ALLOWED_CLASSIFICATIONS:
        raise AnnotationError(
            f"Unsupported classification. Use one of: {', '.join(sorted(ALLOWED_CLASSIFICATIONS))}."
        )
    cleaned_status = _validate_text(verification_status, "verification_status", 64).lower()
    if cleaned_status not in ALLOWED_VERIFICATION_STATUSES:
        raise AnnotationError(
            "Unsupported verification_status. Use one of: "
            f"{', '.join(sorted(ALLOWED_VERIFICATION_STATUSES))}."
        )
    cleaned_authority = _validate_text(authority, "authority", MAX_AUTHORITY_LENGTH)
    if cleaned_authority not in AUTHORIZED_AUTHORITIES:
        raise AnnotationError("Only an authorized HVE authority may create this annotation.")
    cleaned_evidence = (
        _validate_text(evidence, "evidence", MAX_EVIDENCE_LENGTH) if evidence is not None else None
    )

    annotation_dir = root / "state" / "annotations"
    annotation_dir.mkdir(parents=True, exist_ok=True)
    path = _annotation_path(normalized_id, root)
    lock_path = annotation_dir / ".annotations.lock"
    record = {
        "annotation_id": os.urandom(8).hex(),
        "document_id": normalized_id,
        "annotation": cleaned_annotation,
        "classification": cleaned_classification,
        "verification_status": cleaned_status,
        "authority": cleaned_authority,
        "evidence": cleaned_evidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "storage": "append_only_jsonl",
    }

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    return {
        "status": "annotated",
        "document_id": normalized_id,
        "annotation_id": record["annotation_id"],
        "annotation_path": str(path),
        "verification_status": cleaned_status,
        "authority": cleaned_authority,
    }
