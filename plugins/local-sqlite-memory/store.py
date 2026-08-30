"""Profile-local SQLite/FTS5 storage for the local Hermes memory provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse


SCHEMA_VERSION = 3
DEFAULT_DB_NAME = "local-memory.db"
DEFAULT_BACKUP_KEEP = 7
_FTS_TOKEN_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_VALIDITIES = {"current", "review", "expired", "unknown"}
_AUTHORITY_CLASSES = {
    "fact",
    "technical_context",
    "preference",
    "project_context",
    "decision",
    "policy",
    "temporary",
}
_LEDGER_CLASSES = {"decision", "policy"}
_EXPLICIT_AUTHORITY_RE = re.compile(
    r"\b(?:i|we)\s+(?:explicitly\s+)?(?:approve|approved|adopt|adopted|decide|decided)"
    r"\b|\b(?:approved|adopted|effective policy|make this policy|decision:)\b",
    re.IGNORECASE,
)
_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_JSON_FENCE_SEARCH_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL
)
_JSON_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_LOCAL_OLLAMA_HOSTS = {"127.0.0.1", "::1"}
_MAX_EXTRACTION_FACTS = 12
_MAX_EXTRACTION_OUTPUT_CHARS = 20000
_MAX_REPAIR_OUTPUT_CHARS = 12000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    source_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(source_id),
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'conversation',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'candidate', 'superseded', 'archived', 'invalid')),
    validity TEXT NOT NULL DEFAULT 'current'
        CHECK(validity IN ('current', 'review', 'expired', 'unknown')),
    authority_class TEXT NOT NULL DEFAULT 'temporary'
        CHECK(authority_class IN (
            'fact', 'technical_context', 'preference', 'project_context',
            'decision', 'policy', 'temporary'
        )),
    ledger_required INTEGER NOT NULL DEFAULT 0
        CHECK(ledger_required IN (0, 1)),
    valid_from TEXT,
    valid_until TEXT,
    content_sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS idx_memories_recall
    ON memories(status, validity, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_source ON memories(source_id);
CREATE INDEX IF NOT EXISTS idx_sources_session ON sources(session_id, captured_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    category,
    content='memories',
    content_rowid='memory_id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, category)
    VALUES (new.memory_id, new.content, new.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, category)
    VALUES ('delete', old.memory_id, old.content, old.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, category)
    VALUES ('delete', old.memory_id, old.content, old.category);
    INSERT INTO memories_fts(rowid, content, category)
    VALUES (new.memory_id, new.content, new.category);
END;

CREATE TABLE IF NOT EXISTS outbox (
    job_id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('extract_turn', 'consolidate', 'vector_candidate')),
    source_id INTEGER REFERENCES sources(source_id),
    memory_id INTEGER REFERENCES memories(memory_id),
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'reported', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    error_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox(status, created_at, job_id);

CREATE TABLE IF NOT EXISTS vector_candidates (
    candidate_id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL UNIQUE REFERENCES memories(memory_id),
    encoder TEXT NOT NULL DEFAULT '',
    dimensions INTEGER,
    state TEXT NOT NULL DEFAULT 'disabled'
        CHECK(state IN ('disabled', 'pending', 'ready', 'failed')),
    vector BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_reports (
    report_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES outbox(job_id),
    source_id INTEGER NOT NULL REFERENCES sources(source_id),
    mode TEXT NOT NULL CHECK(mode IN ('dry_run', 'promote')),
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'validated', 'promoted', 'model_error', 'malformed', 'unsupported', 'source_error'
    )),
    candidates_json TEXT NOT NULL DEFAULT '[]',
    rejected_json TEXT NOT NULL DEFAULT '[]',
    raw_output TEXT NOT NULL DEFAULT '',
    output_sha256 TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extraction_reports_job
    ON extraction_reports(job_id, report_id DESC);
"""

_HANDOFF_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_handoffs (
    handoff_id INTEGER PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES extraction_reports(report_id),
    job_id INTEGER NOT NULL REFERENCES outbox(job_id),
    source_id INTEGER NOT NULL REFERENCES sources(source_id),
    candidate_index INTEGER NOT NULL,
    candidate_json TEXT NOT NULL,
    decision_text TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'pending_confirmation', 'appended', 'rejected', 'failed'
    )),
    decision_id TEXT NOT NULL DEFAULT '',
    ledger_event_id TEXT NOT NULL DEFAULT '',
    error_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(report_id, candidate_index)
);
CREATE INDEX IF NOT EXISTS idx_ledger_handoffs_status
    ON ledger_handoffs(status, created_at, handoff_id);
"""


class MaintenanceLockError(RuntimeError):
    """Raised when the profile's single maintenance lock is already held."""


class ExtractionError(RuntimeError):
    """A persisted extraction failure with an explicit retry decision."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        report_status: str,
        raw_output: str = "",
        candidates: list[dict[str, Any]] | None = None,
        rejected: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.report_status = report_status
        self.raw_output = raw_output
        self.candidates = candidates or []
        self.rejected = rejected or []


@dataclass(frozen=True)
class ExtractionJob:
    job_id: int
    source_id: int
    memory_id: int
    attempts: int
    user_text: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_db_path(hermes_home: str | Path, configured_path: str = "") -> Path:
    """Resolve an optional profile-relative database path without touching state.db."""
    home = Path(hermes_home).expanduser()
    raw = (configured_path or DEFAULT_DB_NAME).replace("${HERMES_HOME}", str(home))
    raw = raw.replace("$HERMES_HOME", str(home))
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = home / candidate
    return candidate


class LocalMemoryStore:
    """Small, deterministic memory database with source provenance and FTS5."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")
            self._conn.execute("PRAGMA journal_size_limit=67108864")
            try:
                from hermes_state import apply_wal_with_fallback

                apply_wal_with_fallback(self._conn, db_label="local-memory.db")
            except ImportError:
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._migrate_memory_authority()
            self._migrate_outbox_statuses()
            self._conn.executescript(_REPORT_SCHEMA)
            self._conn.executescript(_HANDOFF_SCHEMA)
            self._conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value =
                    CASE
                        WHEN CAST(schema_meta.value AS INTEGER) < excluded.value
                        THEN excluded.value
                        ELSE schema_meta.value
                    END
                """,
                (str(SCHEMA_VERSION),),
            )

    def _migrate_memory_authority(self) -> None:
        """Add authority metadata without rewriting existing source-backed memories."""
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "authority_class" not in columns:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN authority_class TEXT NOT NULL DEFAULT 'temporary'"
            )
        if "ledger_required" not in columns:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN ledger_required INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_outbox_statuses(self) -> None:
        """Add the explicit dry-run-safe ``reported`` status without losing jobs."""
        sql_row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='outbox'"
        ).fetchone()
        if sql_row is None or "'reported'" in str(sql_row["sql"]):
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute("DROP INDEX IF EXISTS idx_outbox_pending")
            self._conn.execute(
                """
                CREATE TABLE outbox_next (
                    job_id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN (
                        'extract_turn', 'consolidate', 'vector_candidate'
                    )),
                    source_id INTEGER REFERENCES sources(source_id),
                    memory_id INTEGER REFERENCES memories(memory_id),
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN (
                            'pending', 'processing', 'reported', 'complete', 'failed'
                        )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    processed_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO outbox_next(
                    job_id, kind, source_id, memory_id, payload_json, status,
                    attempts, error_text, created_at, processed_at
                )
                SELECT job_id, kind, source_id, memory_id, payload_json, status,
                       attempts, error_text, created_at, processed_at
                FROM outbox
                """
            )
            self._conn.execute("DROP TABLE outbox")
            self._conn.execute("ALTER TABLE outbox_next RENAME TO outbox")
            self._conn.execute(
                "CREATE INDEX idx_outbox_pending ON outbox(status, created_at, job_id)"
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def add_turn(
        self,
        *,
        user_content: str,
        assistant_content: str,
        session_id: str,
        platform: str,
        include_assistant: bool,
        vector_candidates_enabled: bool,
    ) -> int | None:
        """Store one source-backed transcript memory and queue offline work."""
        user_content = (user_content or "").strip()
        if not user_content:
            return None
        assistant_content = (assistant_content or "").strip()
        source_body = json.dumps(
            {"user": user_content, "assistant": assistant_content},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(source_body.encode("utf-8")).hexdigest()
        source_ref = f"turn:{session_id or 'unknown'}:{digest}"
        now = utc_now()
        memory_text = f"User: {user_content}"
        if include_assistant and assistant_content:
            memory_text += f"\nAssistant: {assistant_content}"
        truncated = len(memory_text) > 6000
        memory_text = memory_text[:6000]
        category = self._classify(user_content)
        authority_class = "temporary"
        metadata = {
            "capture": "turn",
            "include_assistant": include_assistant,
            "truncated": truncated,
            "vector_candidates_enabled": vector_candidates_enabled,
            "authority_class": authority_class,
            "ledger_required": False,
        }
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO sources(
                        source_type, source_ref, session_id, platform, captured_at,
                        content_sha256, source_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_ref) DO NOTHING
                    """,
                    (
                        "conversation_turn",
                        source_ref,
                        session_id or "",
                        platform or "",
                        now,
                        digest,
                        source_body,
                    ),
                )
                source = self._conn.execute(
                    "SELECT source_id FROM sources WHERE source_ref = ?", (source_ref,)
                ).fetchone()
                if source is None:
                    raise RuntimeError("source insert did not produce a source row")
                source_id = int(source["source_id"])
                content_digest = hashlib.sha256(memory_text.encode("utf-8")).hexdigest()
                self._conn.execute(
                    """
                    INSERT INTO memories(
                        source_id, content, category, status, validity, content_sha256,
                        authority_class, ledger_required, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', 'current', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, content_sha256) DO NOTHING
                    """,
                    (
                        source_id,
                        memory_text,
                        category,
                        content_digest,
                        authority_class,
                        0,
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                        now,
                        now,
                    ),
                )
                memory = self._conn.execute(
                    """
                    SELECT memory_id FROM memories
                    WHERE source_id = ? AND content_sha256 = ?
                    """,
                    (source_id, content_digest),
                ).fetchone()
                if memory is None:
                    raise RuntimeError("memory insert did not produce a memory row")
                memory_id = int(memory["memory_id"])
                self._enqueue_locked(
                    "extract_turn",
                    source_id,
                    memory_id,
                    {"extraction": "deferred", "source_ref": source_ref},
                    now,
                )
                if vector_candidates_enabled:
                    self._conn.execute(
                        """
                        INSERT INTO vector_candidates(
                            memory_id, encoder, state, created_at, updated_at
                        ) VALUES (?, '', 'pending', ?, ?)
                        ON CONFLICT(memory_id) DO NOTHING
                        """,
                        (memory_id, now, now),
                    )
                    self._enqueue_locked(
                        "vector_candidate",
                        source_id,
                        memory_id,
                        {"reason": "optional_vector_extension"},
                        now,
                    )
                self._conn.execute("COMMIT")
                return memory_id
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def add_explicit_memory(
        self, *, content: str, category: str, source_type: str, metadata: dict[str, Any]
    ) -> int | None:
        """Persist a built-in memory write while retaining its local provenance."""
        content = (content or "").strip()
        if not content:
            return None
        now = utc_now()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source_ref = f"{source_type}:{digest}"
        authority_class = str(metadata.get("authority_class") or "fact")
        if authority_class not in _AUTHORITY_CLASSES:
            authority_class = "fact"
        ledger_required = int(authority_class in _LEDGER_CLASSES)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    INSERT INTO sources(
                        source_type, source_ref, captured_at, content_sha256, source_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_ref) DO NOTHING
                    """,
                    (
                        source_type,
                        source_ref,
                        now,
                        digest,
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                    ),
                )
                source = self._conn.execute(
                    "SELECT source_id FROM sources WHERE source_ref = ?", (source_ref,)
                ).fetchone()
                if source is None:
                    raise RuntimeError("explicit memory source was not created")
                self._conn.execute(
                    """
                    INSERT INTO memories(
                        source_id, content, category, status, validity, content_sha256,
                        authority_class, ledger_required, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', 'current', ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, content_sha256) DO UPDATE SET
                        status='active', validity='current',
                        authority_class=excluded.authority_class,
                        ledger_required=excluded.ledger_required,
                        updated_at=excluded.updated_at
                    """,
                    (
                        int(source["source_id"]),
                        content[:6000],
                        category,
                        digest,
                        authority_class,
                        ledger_required,
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                        now,
                        now,
                    ),
                )
                row = self._conn.execute(
                    "SELECT memory_id FROM memories WHERE source_id = ? AND content_sha256 = ?",
                    (int(source["source_id"]), digest),
                ).fetchone()
                self._conn.execute("COMMIT")
                return int(row["memory_id"]) if row else None
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def search(self, query: str, *, limit: int = 5, max_chars: int = 2200) -> list[dict[str, Any]]:
        """Run a bounded lexical FTS5 search; no model or network calls occur here."""
        terms = list(dict.fromkeys(_FTS_TOKEN_RE.findall((query or "").lower())))[:12]
        if not terms:
            return []
        match = " OR ".join(f'"{term}"' for term in terms)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT m.memory_id, m.content, m.category, m.authority_class,
                       m.ledger_required, m.status, m.validity, m.created_at,
                       m.updated_at, m.metadata_json,
                       s.source_type, s.source_ref, s.session_id, s.platform
                FROM memories_fts
                JOIN memories AS m ON m.memory_id = memories_fts.rowid
                JOIN sources AS s ON s.source_id = m.source_id
                WHERE memories_fts MATCH ?
                  AND m.status = 'active'
                  AND m.validity = 'current'
                  AND (m.valid_until IS NULL OR m.valid_until > ?)
                ORDER BY bm25(memories_fts), m.updated_at DESC
                LIMIT ?
                """,
                (match, utc_now(), max(1, min(int(limit), 20))),
            ).fetchall()
        results: list[dict[str, Any]] = []
        used = 0
        for row in rows:
            content = str(row["content"])
            remaining = max_chars - used
            if remaining <= 0:
                break
            if len(content) > remaining:
                content = content[:remaining].rstrip() + " ..."
            item = dict(row)
            item["content"] = content
            results.append(item)
            used += len(content)
        return results

    def maintenance(
        self,
        *,
        process_outbox: bool,
        max_jobs: int,
        backup: bool,
        backup_keep: int = DEFAULT_BACKUP_KEEP,
        dry_run: bool = True,
        rerun_reported: bool = False,
        retry_failed: bool = False,
        extraction_model: str = "qwen3.8-hermes:27b-128k",
        extraction_endpoint: str = "http://127.0.0.1:11434/v1",
        extraction_timeout_seconds: float = 45.0,
        extraction_max_tokens: int = 500,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        """Run bounded offline-only maintenance under a profile-local file lock."""
        with self._maintenance_lock():
            result: dict[str, Any] = {"database": str(self.db_path)}
            if process_outbox:
                result["outbox"] = self._process_outbox(
                    max(1, min(max_jobs, 1000)),
                    dry_run=dry_run,
                    rerun_reported=rerun_reported,
                    retry_failed=retry_failed,
                    model=extraction_model,
                    endpoint=extraction_endpoint,
                    timeout_seconds=max(1.0, min(float(extraction_timeout_seconds), 120.0)),
                    max_tokens=max(32, min(int(extraction_max_tokens), 1000)),
                    max_attempts=max(1, min(int(max_attempts), 5)),
                )
            with self._lock:
                result["consolidation"] = self._consolidate_locked(limit=100)
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
                self._conn.execute(
                    "INSERT INTO memories_fts(memories_fts, rank) VALUES ('merge', 4)"
                )
                self._conn.execute("PRAGMA optimize").fetchall()
                integrity = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"integrity_check failed: {integrity}")
                result["integrity_check"] = integrity
                result["memory_count"] = self._conn.execute(
                    "SELECT COUNT(*) FROM memories WHERE status = 'active'"
                ).fetchone()[0]
                result["pending_outbox"] = self._conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
                ).fetchone()[0]
                result["reported_outbox"] = self._conn.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status = 'reported'"
                ).fetchone()[0]
                if backup:
                    result["backup"] = str(self._backup_locked(backup_keep))
            return result

    def _process_outbox(
        self,
        max_jobs: int,
        *,
        dry_run: bool,
        rerun_reported: bool,
        retry_failed: bool,
        model: str,
        endpoint: str,
        timeout_seconds: float,
        max_tokens: int,
        max_attempts: int,
    ) -> dict[str, Any]:
        """Run one-at-a-time local extraction without holding a DB transaction for inference."""
        counters = {
            "completed": 0,
            "failed": 0,
            "reported": 0,
            "retryable": 0,
            "examined": 0,
            "ledger_handoffs": 0,
            "reports": [],
        }
        self._recover_interrupted_jobs(max_attempts)
        for _ in range(max_jobs):
            job = self._claim_next_job(rerun_reported, retry_failed, max_attempts)
            if job is None:
                break
            counters["examined"] += 1
            try:
                raw_output, candidates = self._extract_candidates(
                    job.user_text,
                    model=model,
                    endpoint=endpoint,
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                )
                if dry_run:
                    report_id = self._record_report(
                        job,
                        mode="dry_run",
                        model=model,
                        endpoint=endpoint,
                        status="validated",
                        candidates=candidates,
                        rejected=[],
                        raw_output=raw_output,
                        error_text="",
                        outbox_status="reported",
                    )
                    counters["ledger_handoffs"] += self._record_ledger_handoffs(
                        job, report_id, candidates
                    )
                    counters["reported"] += 1
                    counters["reports"].append(
                        {
                            "candidate_count": len(candidates),
                            "job_id": job.job_id,
                            "report_id": report_id,
                            "status": "validated",
                        }
                    )
                else:
                    report_id = self._promote_candidates(
                        job,
                        model=model,
                        endpoint=endpoint,
                        candidates=candidates,
                        raw_output=raw_output,
                    )
                    counters["ledger_handoffs"] += self._record_ledger_handoffs(
                        job, report_id, candidates
                    )
                    counters["completed"] += 1
                    counters["reports"].append(
                        {
                            "candidate_count": len(candidates),
                            "job_id": job.job_id,
                            "report_id": report_id,
                            "status": "promoted",
                        }
                    )
            except ExtractionError as exc:
                outcome, report_id = self._record_extraction_failure(
                    job,
                    mode="dry_run" if dry_run else "promote",
                    model=model,
                    endpoint=endpoint,
                    error=exc,
                    max_attempts=max_attempts,
                )
                counters[outcome] += 1
                counters["reports"].append(
                    {
                        "candidate_count": len(exc.candidates),
                        "job_id": job.job_id,
                        "report_id": report_id,
                        "status": exc.report_status,
                    }
                )
            except Exception as exc:
                error = ExtractionError(
                    f"unexpected extractor failure: {type(exc).__name__}: {exc}",
                    retryable=False,
                    report_status="model_error",
                )
                outcome, report_id = self._record_extraction_failure(
                    job,
                    mode="dry_run" if dry_run else "promote",
                    model=model,
                    endpoint=endpoint,
                    error=error,
                    max_attempts=max_attempts,
                )
                counters[outcome] += 1
                counters["reports"].append(
                    {
                        "candidate_count": 0,
                        "job_id": job.job_id,
                        "report_id": report_id,
                        "status": error.report_status,
                    }
                )
        return counters

    def _recover_interrupted_jobs(self, max_attempts: int) -> None:
        """Make jobs left by a terminated maintenance process retryable exactly once more."""
        now = utc_now()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """
                    UPDATE outbox
                    SET status='failed',
                        error_text='interrupted extraction exhausted retry limit',
                        processed_at=?
                    WHERE status='processing' AND attempts >= ?
                    """,
                    (now, max_attempts),
                )
                self._conn.execute(
                    """
                    UPDATE outbox
                    SET status='pending',
                        error_text='recovered after interrupted maintenance',
                        processed_at=NULL
                    WHERE status='processing' AND attempts < ?
                    """,
                    (max_attempts,),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _claim_next_job(
        self, rerun_reported: bool, retry_failed: bool, max_attempts: int
    ) -> ExtractionJob | None:
        """Claim exactly one eligible extraction job in a short transaction."""
        statuses = ["pending"]
        if rerun_reported:
            statuses.append("reported")
        if retry_failed:
            statuses.append("failed")
        marks = ", ".join("?" for _ in statuses)
        source_json = ""
        job: ExtractionJob | None = None
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    f"""
                    SELECT o.job_id, o.source_id, o.memory_id, o.attempts, s.source_json
                    FROM outbox AS o
                    LEFT JOIN sources AS s ON s.source_id = o.source_id
                    WHERE o.kind='extract_turn' AND o.status IN ({marks})
                      AND o.attempts < ?
                    ORDER BY o.job_id
                    LIMIT 1
                    """,
                    (*statuses, max_attempts),
                ).fetchone()
                if row is None:
                    self._conn.execute("COMMIT")
                    return None
                job_id = int(row["job_id"])
                source_id = row["source_id"]
                memory_id = row["memory_id"]
                if source_id is None or memory_id is None:
                    self._conn.execute(
                        """
                        UPDATE outbox
                        SET status='failed', attempts=attempts + 1,
                            error_text='extract_turn job has no source-backed memory',
                            processed_at=?
                        WHERE job_id=?
                        """,
                        (utc_now(), job_id),
                    )
                    self._conn.execute("COMMIT")
                    return None
                self._conn.execute(
                    """
                    UPDATE outbox
                    SET status='processing', attempts=attempts + 1,
                        error_text='', processed_at=NULL
                    WHERE job_id=?
                    """,
                    (job_id,),
                )
                self._conn.execute("COMMIT")
                source_json = str(row["source_json"])
                job = ExtractionJob(
                    job_id=job_id,
                    source_id=int(source_id),
                    memory_id=int(memory_id),
                    attempts=int(row["attempts"]) + 1,
                    user_text="",
                )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        try:
            source = json.loads(source_json)
            user_text = source["user"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ExtractionError(
                f"stored turn source has no valid user text: {exc}",
                retryable=False,
                report_status="source_error",
            ) from exc
        if not isinstance(user_text, str) or not user_text.strip():
            raise ExtractionError(
                "stored turn source has empty user text",
                retryable=False,
                report_status="source_error",
            )
        if job is None:
            raise RuntimeError("claimed outbox job was not constructed")
        return ExtractionJob(
            job_id=job.job_id,
            source_id=job.source_id,
            memory_id=job.memory_id,
            attempts=job.attempts,
            user_text=user_text,
        )

    def _extract_candidates(
        self,
        user_text: str,
        *,
        model: str,
        endpoint: str,
        timeout_seconds: float,
        max_tokens: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Ask only the loopback Ollama OpenAI endpoint for strict candidate JSON."""
        parsed = urlparse(endpoint)
        try:
            is_safe_endpoint = (
                parsed.scheme == "http"
                and parsed.hostname in _LOCAL_OLLAMA_HOSTS
                and parsed.port == 11434
                and not parsed.username
                and not parsed.password
                and parsed.path.rstrip("/") == "/v1"
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            is_safe_endpoint = False
        if not is_safe_endpoint:
            raise ExtractionError(
                "extraction endpoint must be the loopback http://127.0.0.1:11434/v1 endpoint",
                retryable=False,
                report_status="model_error",
            )
        if not model or model != "qwen3.8-hermes:27b-128k":
            raise ExtractionError(
                "only the approved local 27B extraction model is permitted",
                retryable=False,
                report_status="model_error",
            )
        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
        except ImportError as exc:
            raise ExtractionError(
                "OpenAI-compatible client is not installed in the Hermes venv",
                retryable=False,
                report_status="model_error",
            ) from exc
        prompt_text = user_text[:12000]
        system_prompt = (
            "Return exactly one JSON object, no markdown. Extract only durable semantic "
            "facts explicitly stated in USER TEXT. Never use assistant text, infer, or "
            "guess. Schema: {\"facts\":[{\"classification\":\"fact|technical_context|"
            "preference|project_context|decision|policy|temporary\",\"fact\":\"CONCISE "
            "SUPPORTED FACT\",\"quote\":\"EXACT QUOTE\",\"confidence\":0.0,\"validity\":"
            "\"current\",\"durable\":true}]}. quote MUST be an exact substring of USER TEXT; "
            "fact must be a concise statement directly supported by quote. Use [] for "
            "greetings, acknowledgements, questions, transient requests, "
            "or unsupported content. Classify technical architecture and operational facts "
            "as technical_context. Use decision or policy only when USER TEXT contains "
            "explicit adoption or approval language such as 'I approve', 'we decided', "
            "'adopted', or 'make this policy'. 'Remember this', persistence, implementation, "
            "or recommendation alone never establishes decision or policy authority. "
            "ledger_required is derived by the validator and must not be returned. "
            "Allowed validity: current, review, expired, unknown."
        )
        repair_system_prompt = (
            "Repair the local extractor response. Return exactly one JSON object, "
            "no markdown or commentary. The only valid shape is {\"facts\":[{"
            "\"classification\":\"fact|technical_context|preference|project_context|"
            "decision|policy|temporary\",\"fact\":\"short supported statement\","
            "\"quote\":\"exact substring from USER TEXT\",\"confidence\":0.0,"
            "\"validity\":\"current|review|expired|unknown\",\"durable\":true}]}. "
            "Do not return strings in facts. Do not add facts, rewrite quotes, infer "
            "meaning, or use anything outside USER TEXT. For example, USER TEXT "
            "'I prefer concise answers.' may produce {\"facts\":[{\"classification\":"
            "\"preference\",\"fact\":\"The user prefers concise answers.\",\"quote\":"
            "\"I prefer concise answers.\",\"confidence\":0.95,\"validity\":\"current\","
            "\"durable\":true}]}. If it cannot be repaired safely, return {\"facts\":[]}."
        )
        try:
            client = OpenAI(
                base_url=endpoint.rstrip("/") + "/",
                api_key="local-only",
                timeout=timeout_seconds,
                max_retries=0,
            )
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                extra_body={"think": False},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"user_text": prompt_text}, ensure_ascii=True, separators=(",", ":")
                        ),
                    },
                ],
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise ExtractionError(
                f"local extraction model unavailable: {type(exc).__name__}: {exc}",
                retryable=True,
                report_status="model_error",
            ) from exc
        except APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code == 429
            raise ExtractionError(
                f"local extraction model returned HTTP {exc.status_code}: {exc}",
                retryable=retryable,
                report_status="model_error",
            ) from exc
        except Exception as exc:
            raise ExtractionError(
                f"local extraction client failure: {type(exc).__name__}: {exc}",
                retryable=False,
                report_status="model_error",
            ) from exc
        try:
            initial_output = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise ExtractionError(
                f"local extraction response has no message content: {exc}",
                retryable=True,
                report_status="model_error",
            ) from exc
        if not isinstance(initial_output, str) or not initial_output.strip():
            raise ExtractionError(
                "local extraction response content is empty",
                retryable=True,
                report_status="model_error",
            )
        initial_output = initial_output[:_MAX_EXTRACTION_OUTPUT_CHARS]

        def normalize_json_output(raw_output: str) -> str:
            normalized_output = raw_output
            fenced = _JSON_FENCE_RE.fullmatch(raw_output)
            if fenced:
                normalized_output = fenced.group(1).strip()
            else:
                fenced_match = _JSON_FENCE_SEARCH_RE.search(raw_output)
                if fenced_match:
                    normalized_output = fenced_match.group(1).strip()
                else:
                    normalized_output = _JSON_FENCE_OPEN_RE.sub("", raw_output, count=1).strip()
                    if normalized_output.endswith("```"):
                        normalized_output = normalized_output[:-3].rstrip()
            if normalized_output.endswith("."):
                normalized_output = normalized_output[:-1].rstrip()
            return normalized_output

        try:
            payload = json.loads(normalize_json_output(initial_output))
            return initial_output, self._validate_candidates(payload, user_text, initial_output)
        except json.JSONDecodeError:
            pass

        repair_input = json.dumps(
            {
                "user_text": prompt_text,
                "invalid_response": initial_output[:_MAX_REPAIR_OUTPUT_CHARS],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
        try:
            repair_response = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                extra_body={"think": False},
                messages=[
                    {"role": "system", "content": repair_system_prompt},
                    {"role": "user", "content": repair_input},
                ],
            )
            repaired_output = repair_response.choices[0].message.content
        except (APIConnectionError, APITimeoutError) as exc:
            raise ExtractionError(
                f"local extraction repair unavailable: {type(exc).__name__}: {exc}",
                retryable=True,
                report_status="model_error",
                raw_output=initial_output,
            ) from exc
        except APIStatusError as exc:
            retryable = exc.status_code >= 500 or exc.status_code == 429
            raise ExtractionError(
                f"local extraction repair returned HTTP {exc.status_code}: {exc}",
                retryable=retryable,
                report_status="model_error",
                raw_output=initial_output,
            ) from exc
        except Exception as exc:
            raise ExtractionError(
                f"local extraction repair failure: {type(exc).__name__}: {exc}",
                retryable=False,
                report_status="model_error",
                raw_output=initial_output,
            ) from exc
        if not isinstance(repaired_output, str) or not repaired_output.strip():
            raise ExtractionError(
                "local extraction repair response content is empty",
                retryable=False,
                report_status="malformed",
                raw_output=initial_output,
            )
        repaired_output = repaired_output[:_MAX_EXTRACTION_OUTPUT_CHARS]
        raw_output = (
            "initial_response:\n"
            + initial_output
            + "\nrepair_response:\n"
            + repaired_output
        )
        try:
            payload = json.loads(normalize_json_output(repaired_output))
        except json.JSONDecodeError as exc:
            raise ExtractionError(
                f"local extraction output and bounded repair are not strict JSON: {exc.msg}",
                retryable=False,
                report_status="malformed",
                raw_output=raw_output,
            ) from exc
        return raw_output, self._validate_candidates(payload, user_text, raw_output)

    def _validate_candidates(
        self, payload: Any, user_text: str, raw_output: str
    ) -> list[dict[str, Any]]:
        """Require directly quoted, non-invented semantic candidates before reporting."""
        if not isinstance(payload, dict) or set(payload) != {"facts"}:
            raise ExtractionError(
                "local extraction JSON must contain exactly one facts array",
                retryable=False,
                report_status="malformed",
                raw_output=raw_output,
            )
        facts = payload["facts"]
        if not isinstance(facts, list) or len(facts) > _MAX_EXTRACTION_FACTS:
            raise ExtractionError(
                f"facts must be an array of at most {_MAX_EXTRACTION_FACTS} items",
                retryable=False,
                report_status="malformed",
                raw_output=raw_output,
            )
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        required = {
            "classification", "fact", "quote", "confidence", "validity", "durable"
        }
        for index, fact in enumerate(facts):
            reason = ""
            if not isinstance(fact, dict) or set(fact) != required:
                reason = "candidate fields must exactly match the required schema"
            else:
                classification = fact["classification"]
                quote = fact["quote"]
                concise_fact = fact["fact"]
                confidence = fact["confidence"]
                validity = fact["validity"]
                durable = fact["durable"]
                if classification not in _AUTHORITY_CLASSES:
                    reason = "invalid authority classification"
                elif not isinstance(quote, str) or not quote or len(quote) > 2000:
                    reason = "invalid quote"
                elif quote not in user_text:
                    reason = "quote does not exactly match stored user text"
                elif (
                    not isinstance(concise_fact, str)
                    or not concise_fact.strip()
                    or len(concise_fact) > 500
                    or "\n" in concise_fact
                ):
                    reason = "fact must be a concise single-line statement"
                elif isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    reason = "confidence must be a number"
                elif not 0.0 <= float(confidence) <= 1.0:
                    reason = "confidence must be between zero and one"
                elif validity not in _VALIDITIES:
                    reason = "invalid validity"
                elif not isinstance(durable, bool):
                    reason = "durable must be boolean"
                elif classification in _LEDGER_CLASSES and not _EXPLICIT_AUTHORITY_RE.search(
                    user_text
                ):
                    reason = (
                        "decision or policy requires explicit approval or adoption language"
                    )
            if reason:
                rejected.append({"index": index, "reason": reason})
                continue
            accepted.append(
                {
                    "classification": classification,
                    "fact": concise_fact,
                    "quote": quote,
                    "confidence": float(confidence),
                    "validity": validity,
                    "durable": durable,
                    "ledger_required": classification in _LEDGER_CLASSES,
                }
            )
        if rejected:
            raise ExtractionError(
                "local extraction returned unsupported candidate facts",
                retryable=False,
                report_status="unsupported",
                raw_output=raw_output,
                candidates=accepted,
                rejected=rejected,
            )
        return accepted

    def _record_report(
        self,
        job: ExtractionJob,
        *,
        mode: str,
        model: str,
        endpoint: str,
        status: str,
        candidates: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        raw_output: str,
        error_text: str,
        outbox_status: str,
    ) -> int:
        """Persist a report and terminal/safe outbox status atomically after inference."""
        now = utc_now()
        output_sha256 = hashlib.sha256(raw_output.encode("utf-8")).hexdigest() if raw_output else ""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._conn.execute(
                    """
                    INSERT INTO extraction_reports(
                        job_id, source_id, mode, model, endpoint, status,
                        candidates_json, rejected_json, raw_output, output_sha256,
                        error_text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.source_id,
                        mode,
                        model,
                        endpoint,
                        status,
                        json.dumps(candidates, ensure_ascii=True, sort_keys=True),
                        json.dumps(rejected, ensure_ascii=True, sort_keys=True),
                        raw_output,
                        output_sha256,
                        error_text[:1000],
                        now,
                    ),
                )
                updated = self._conn.execute(
                    """
                    UPDATE outbox
                    SET status=?, error_text=?, processed_at=?
                    WHERE job_id=? AND status='processing'
                    """,
                    (outbox_status, error_text[:1000], now, job.job_id),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("claimed outbox job no longer has processing status")
                self._conn.execute("COMMIT")
                return int(cursor.lastrowid)
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _record_extraction_failure(
        self,
        job: ExtractionJob,
        *,
        mode: str,
        model: str,
        endpoint: str,
        error: ExtractionError,
        max_attempts: int,
    ) -> tuple[str, int]:
        """Record failures, retaining only bounded retries for transient local model errors."""
        outcome = "retryable" if error.retryable and job.attempts < max_attempts else "failed"
        report_id = self._record_report(
            job,
            mode=mode,
            model=model,
            endpoint=endpoint,
            status=error.report_status,
            candidates=error.candidates,
            rejected=error.rejected,
            raw_output=error.raw_output,
            error_text=str(error),
            outbox_status="pending" if outcome == "retryable" else "failed",
        )
        return outcome, report_id

    def _record_ledger_handoffs(
        self,
        job: ExtractionJob,
        report_id: int,
        candidates: list[dict[str, Any]],
    ) -> int:
        """Persist decision/policy candidates for explicit governed confirmation."""
        now = utc_now()
        inserted = 0
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for index, candidate in enumerate(candidates):
                    if not candidate.get("ledger_required"):
                        continue
                    cursor = self._conn.execute(
                        """
                        INSERT INTO ledger_handoffs(
                            report_id, job_id, source_id, candidate_index,
                            candidate_json, decision_text, status,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'pending_confirmation', ?, ?)
                        ON CONFLICT(report_id, candidate_index) DO NOTHING
                        """,
                        (
                            report_id,
                            job.job_id,
                            job.source_id,
                            index,
                            json.dumps(candidate, ensure_ascii=True, sort_keys=True),
                            candidate["fact"],
                            now,
                            now,
                        ),
                    )
                    inserted += max(0, int(cursor.rowcount))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return inserted

    def list_ledger_handoffs(
        self, *, status: str = "pending_confirmation", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return durable handoff proposals without writing to the decision ledger."""
        if status not in {"pending_confirmation", "appended", "rejected", "failed"}:
            raise ValueError(f"invalid ledger handoff status: {status}")
        rows = self._conn.execute(
            """
            SELECT handoff_id, report_id, job_id, source_id, candidate_index,
                   candidate_json, decision_text, status, decision_id,
                   ledger_event_id, error_text, created_at, updated_at
            FROM ledger_handoffs
            WHERE status=?
            ORDER BY handoff_id
            LIMIT ?
            """,
            (status, max(1, min(int(limit), 200))),
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["candidate"] = json.loads(item.pop("candidate_json"))
            results.append(item)
        return results

    def _promote_candidates(
        self,
        job: ExtractionJob,
        *,
        model: str,
        endpoint: str,
        candidates: list[dict[str, Any]],
        raw_output: str,
    ) -> int:
        """Promote validated facts while keeping ledger-bound items reviewable."""
        now = utc_now()
        promoted = 0
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for candidate in candidates:
                    if not candidate["durable"]:
                        continue
                    content = candidate["fact"]
                    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    ledger_required = bool(candidate["ledger_required"])
                    status = "candidate" if ledger_required else "active"
                    metadata = {
                        "capture": "semantic_extraction",
                        "confidence": candidate["confidence"],
                        "durable": True,
                        "quote": candidate["quote"],
                        "authority_class": candidate["classification"],
                        "ledger_required": ledger_required,
                    }
                    cursor = self._conn.execute(
                        """
                        INSERT INTO memories(
                            source_id, content, category, status, validity, content_sha256,
                            authority_class, ledger_required, metadata_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_id, content_sha256) DO NOTHING
                        """,
                        (
                            job.source_id,
                            content,
                            candidate["classification"],
                            status,
                            candidate["validity"],
                            digest,
                            candidate["classification"],
                            int(ledger_required),
                            json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                            now,
                            now,
                        ),
                    )
                    promoted += max(0, int(cursor.rowcount))
                output_sha256 = hashlib.sha256(raw_output.encode("utf-8")).hexdigest()
                cursor = self._conn.execute(
                    """
                    INSERT INTO extraction_reports(
                        job_id, source_id, mode, model, endpoint, status,
                        candidates_json, rejected_json, raw_output, output_sha256,
                        error_text, created_at
                    ) VALUES (?, ?, 'promote', ?, ?, 'promoted', ?, '[]', ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.source_id,
                        model,
                        endpoint,
                        json.dumps(candidates, ensure_ascii=True, sort_keys=True),
                        raw_output,
                        output_sha256,
                        f"promoted_durable_candidates={promoted}",
                        now,
                    ),
                )
                updated = self._conn.execute(
                    """
                    UPDATE outbox
                    SET status='complete', error_text=?, processed_at=?
                    WHERE job_id=? AND status='processing'
                    """,
                    (f"promoted_durable_candidates={promoted}", now, job.job_id),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("claimed outbox job no longer has processing status")
                self._conn.execute("COMMIT")
                return int(cursor.lastrowid)
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _consolidate_locked(self, limit: int) -> dict[str, int]:
        """Conservatively supersede exact duplicate active memories offline."""
        duplicate_hashes = self._conn.execute(
            """
            SELECT content_sha256
            FROM memories
            WHERE status = 'active' AND validity = 'current'
            GROUP BY content_sha256
            HAVING COUNT(*) > 1
            ORDER BY MIN(memory_id)
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        superseded = 0
        now = utc_now()
        for row in duplicate_hashes:
            content_sha256 = row["content_sha256"]
            keeper = self._conn.execute(
                """
                SELECT memory_id FROM memories
                WHERE content_sha256 = ? AND status = 'active' AND validity = 'current'
                ORDER BY memory_id LIMIT 1
                """,
                (content_sha256,),
            ).fetchone()
            if keeper is None:
                continue
            changed = self._conn.execute(
                """
                UPDATE memories
                SET status = 'superseded', updated_at = ?
                WHERE content_sha256 = ? AND status = 'active' AND validity = 'current'
                  AND memory_id != ?
                """,
                (now, content_sha256, int(keeper["memory_id"])),
            ).rowcount
            superseded += max(0, int(changed))
        return {"duplicate_groups": len(duplicate_hashes), "superseded": superseded}

    def _backup_locked(self, keep: int) -> Path:
        backup_dir = self.db_path.parent / "backups" / "local-memory"
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{self.db_path.stem}-{stamp}.db"
        destination = sqlite3.connect(target)
        try:
            self._conn.backup(destination)
        finally:
            destination.close()
        os.chmod(target, 0o600)
        snapshots = sorted(backup_dir.glob(f"{self.db_path.stem}-*.db"), reverse=True)
        for stale in snapshots[max(1, keep):]:
            stale.unlink()
        return target

    def _enqueue_locked(
        self, kind: str, source_id: int, memory_id: int, payload: dict[str, Any], now: str
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO outbox(kind, source_id, memory_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (kind, source_id, memory_id, json.dumps(payload, ensure_ascii=True), now),
        )

    @staticmethod
    def _classify(content: str) -> str:
        lower = content.lower()
        if any(token in lower for token in ("i prefer", "i always", "i never", "my preferred")):
            return "preference"
        if any(token in lower for token in ("we decided", "we agreed", "decision:", "approved")):
            return "decision"
        if any(token in lower for token in ("remember", "important", "constraint")):
            return "reference"
        return "conversation"

    @contextmanager
    def _maintenance_lock(self) -> Iterator[None]:
        import fcntl

        lock_path = self.db_path.with_name(f"{self.db_path.name}.maintenance.lock")
        handle = open(lock_path, "a+", encoding="ascii")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MaintenanceLockError(
                    f"maintenance already running for {self.db_path}"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
