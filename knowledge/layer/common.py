#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import yaml


CONFIG_PATH = Path.home() / "hanshermesagent" / "config" / "knowledge-layer" / "knowledge-layer.yaml"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_failure(root: Path, document_id: str, stage: str, error: str) -> None:
    failed_dir = root / "state" / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "document_id": document_id,
        "stage": stage,
        "error": error,
        "recorded_at": now_iso(),
    }
    (failed_dir / f"{document_id}-{stage}.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_failure(root: Path, document_id: str, stage: str) -> None:
    target = root / "state" / "failed" / f"{document_id}-{stage}.json"
    if target.exists():
        target.unlink()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_whitespace(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def split_pdf_pages(text: str) -> list[str]:
    pages = [page.strip() for page in text.split("\f")]
    return [page for page in pages if page]


def parse_filename_metadata(source_path: str) -> dict:
    stem = Path(source_path).stem.replace("_", " ").strip()
    parts = [part.strip() for part in stem.split(" -- ") if part.strip()]
    title = parts[0] if parts else stem
    author = parts[1] if len(parts) > 1 else None

    year_match = re.search(r"(19|20)\d{2}", stem)
    publication_year = int(year_match.group(0)) if year_match else None

    publisher = None
    if len(parts) > 2:
        candidates = [part for part in parts[2:] if not re.fullmatch(r"(19|20)\d{2}", part)]
        publisher = candidates[-1] if candidates else None

    return {
        "book": title,
        "title": title,
        "author": author,
        "publisher": publisher,
        "publication_year": publication_year,
    }


def guess_chapter(page_text: str) -> str:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    if not lines:
        return "Unknown"

    for index, line in enumerate(lines[:20]):
        upperish = line == line.upper()
        titleish = line.istitle()
        if 3 <= len(line) <= 120 and not line.startswith("http"):
            if re.match(r"^(chapter|section|part)\b", line, re.IGNORECASE):
                if index + 1 < len(lines) and len(lines[index + 1]) <= 120:
                    return f"{line} — {lines[index + 1]}"
                return line
            if upperish or titleish:
                return line
    return lines[0][:120]


def iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)
