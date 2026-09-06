"""Private Phase 0 tasking workflow for the Hans WhatsApp DM pilot.

This module deliberately has no GitHub or WhatsApp transport.  The pilot backend
is a local SQLite control plane and an isolated artifact directory.  A later
phase may add adapters after Hans approves the private UX.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PILLARS = {"Time", "Physical", "Mental", "Social", "Financial"}
STATES = {"draft", "open", "in_progress", "blocked", "awaiting_validation", "done"}
SENSITIVITY_CLASSES = {"public", "financial", "health", "tax", "strategic", "credential", "restricted"}
ALLOWED_TRANSITIONS = {
    "starting": {"open", "blocked"},
    "blocked": {"open", "in_progress"},
    "retry": {"blocked"},
    "artifact_delivery": {"open", "in_progress"},
    "done": {"open", "in_progress"},
    "approve_validation": {"awaiting_validation"},
    "reject_validation": {"awaiting_validation"},
}
DELIVERY_CONFIRMED_STATUSES = {
    "artifact_confirmed",
    "duplicate_artifact_delivery",
}
SENSITIVE_PATTERNS = {
    "financial": re.compile(r"\b(iul|investment|investing|bank|budget|financial|treasury|trading|kraken|bitcoin|crypto|wallet)\b", re.I),
    "health": re.compile(r"\b(health|medical|diagnos|nutrition|diet|therapy|medication|patient)\b", re.I),
    "tax": re.compile(r"\b(tax|cra|income|vat|gst|taxpayer)\b", re.I),
    "strategic": re.compile(r"\b(strategy|strategic|confidential|restricted|nonpublic|roadmap)\b", re.I),
    "credential": re.compile(r"\b(password|passphrase|token|api[_ -]?key|secret|credential|private key)\b", re.I),
}


class PilotError(ValueError):
    """A safe, user-visible pilot validation or state error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _text(value: Any, field: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise PilotError(f"{field} is required; no task was created.")
        return ""
    result = str(value).strip()
    if required and not result:
        raise PilotError(f"{field} is required; no task was created.")
    return result


def _line_count(content: bytes) -> int:
    return len(content.splitlines())


def classify_sensitivity(values: list[str]) -> str:
    combined = "\n".join(values)
    for classification, pattern in SENSITIVE_PATTERNS.items():
        if pattern.search(combined):
            return classification
    return "public"


class PilotStore:
    """Transactional local backend with append-only task events."""

    def __init__(
        self,
        db_path: str | Path,
        artifact_root: str | Path | None = None,
        *,
        task_prefix: str = "P0",
        backend_name: str = "private-phase-0-local",
        public_repository: str = "not_configured_private_phase_0",
        enforce_sensitivity_gate: bool = True,
        enforce_reserved_al01_gate: bool = True,
        defer_artifact_validation: bool = False,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.artifact_root = Path(
            artifact_root
            or self.db_path.parent / "team-tasking-pilot-artifacts"
        ).expanduser()
        self.task_prefix = task_prefix
        self.backend_name = backend_name
        self.public_repository = public_repository
        self.enforce_sensitivity_gate = enforce_sensitivity_gate
        self.enforce_reserved_al01_gate = enforce_reserved_al01_gate
        self.defer_artifact_validation = defer_artifact_validation
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    source_message_id TEXT NOT NULL UNIQUE,
                    source_message TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    deliverable TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    due_date TEXT,
                    acceptance_criteria TEXT NOT NULL,
                    risks TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    team_message TEXT NOT NULL,
                    pending_action TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    source_message TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    requested_transition TEXT NOT NULL,
                    result TEXT NOT NULL,
                    reason TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, sha256)
                );
                """
            )

    def _event(
        self,
        db: sqlite3.Connection,
        *,
        event_key: str,
        source_message: str,
        actor: str,
        task_id: str,
        requested_transition: str,
        result: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO events
              (event_key, source_message, actor, occurred_at, task_id,
               requested_transition, result, reason, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                source_message,
                actor,
                _utc_now(),
                task_id,
                requested_transition,
                result,
                reason,
                _json(metadata or {}),
            ),
        )
        return cursor.rowcount == 1

    def normalize(
        self,
        *,
        source_message_id: str,
        source_message: str,
        owner: str,
        deliverable: str,
        pillar: str,
        due_date: str | None = None,
        acceptance_criteria: list[str] | None = None,
        risks: list[str] | None = None,
        actor: str = "Hans",
    ) -> dict[str, Any]:
        message_id = _text(source_message_id, "source_message_id")
        source = _text(source_message, "source_message")
        owner_value = _text(owner, "owner")
        deliverable_value = _text(deliverable, "deliverable")
        pillar_value = _text(pillar, "pillar")
        if pillar_value not in PILLARS:
            raise PilotError(f"pillar must be one of {sorted(PILLARS)}; no task was created.")
        if self.enforce_reserved_al01_gate and re.search(
            r"\bAL-01\b|Alan['’]?s updated bio", f"{deliverable_value} {source}", re.I
        ):
            raise PilotError("AL-01 is reserved until the Phase 0 pilot passes; no task was created.")
        criteria = acceptance_criteria or []
        if not criteria or any(not str(item).strip() for item in criteria):
            raise PilotError("acceptance_criteria must contain at least one explicit criterion; no task was created.")
        criteria = [str(item).strip() for item in criteria]
        risk_values = [str(item).strip() for item in (risks or []) if str(item).strip()]
        sensitivity = classify_sensitivity([source, deliverable_value, *criteria, *risk_values])
        task_id = f"{self.task_prefix}-{hashlib.sha256(message_id.encode()).hexdigest()[:12].upper()}"
        card = {
            "task_id": task_id,
            "source_message": source,
            "title": deliverable_value,
            "owner": owner_value,
            "deliverable": deliverable_value,
            "pillar": pillar_value,
            "due_date": due_date or None,
            "acceptance_criteria": criteria,
            "risks": risk_values,
            "sensitivity": sensitivity,
            "public_repository": (
                "blocked_by_sensitivity_gate"
                if self.enforce_sensitivity_gate and sensitivity != "public"
                else self.public_repository
            ),
            "initial_state": "open",
            "backend": self.backend_name,
        }
        team_message = (
            f"[PILOT DRAFT] {task_id} — {deliverable_value}\n"
            f"Owner: {owner_value} | Pillar: {pillar_value}"
            + (f" | Due: {due_date}" if due_date else "")
            + "\nReport starting, blockers, artifact delivery, and done in the designated channel."
        )
        now = _utc_now()
        with self._connect() as db:
            existing = db.execute(
                "SELECT * FROM tasks WHERE source_message_id = ?", (message_id,)
            ).fetchone()
            if existing:
                return self._task_result(existing, "duplicate_preview")
            db.execute(
                """
                INSERT INTO tasks
                  (task_id, source_message_id, source_message, owner, deliverable,
                   pillar, due_date, acceptance_criteria, risks, sensitivity, state,
                   card_json, team_message, pending_action, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, NULL, ?, ?)
                """,
                (
                    task_id, message_id, source, owner_value, deliverable_value,
                    pillar_value, due_date, _json(criteria), _json(risk_values),
                    sensitivity, _json(card), team_message, now, now,
                ),
            )
            self._event(
                db, event_key=f"{message_id}:normalized", source_message=source,
                actor=actor, task_id=task_id, requested_transition="normalize",
                result="preview_ready",
                metadata={
                    "sensitivity": sensitivity,
                    "sensitivity_gate_enforced": self.enforce_sensitivity_gate,
                },
            )
            row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._task_result(row, "preview_ready")

    def approve(self, task_id: str, *, approval_message_id: str, actor: str = "Hans") -> dict[str, Any]:
        current = self._get(task_id)
        if (
            current["state"] == "open"
            and current["pending_action"] == "create GitHub tracking record"
        ):
            return self._task_result(current, "retry_external")
        return self._transition(
            task_id, event_key=f"{approval_message_id}:approve", source_message=approval_message_id,
            actor=actor, requested="approve_task", allowed={"draft"}, new_state="open",
            metadata={
                "public_repository": (
                    "blocked"
                    if self.enforce_sensitivity_gate and self._sensitivity(task_id) != "public"
                    else self.public_repository
                ),
                "sensitivity_gate_enforced": self.enforce_sensitivity_gate,
            },
        )

    def starting(self, task_id: str, *, source_message: str, event_id: str, actor: str = "Hans") -> dict[str, Any]:
        return self._transition(task_id, event_key=f"{event_id}:starting", source_message=source_message,
                               actor=actor, requested="starting", allowed={"open", "blocked"}, new_state="in_progress")

    def block(self, task_id: str, *, reason: str, source_message: str, event_id: str, actor: str = "Hans") -> dict[str, Any]:
        return self._transition(task_id, event_key=f"{event_id}:blocked", source_message=source_message,
                               actor=actor, requested="blocked", allowed={"open", "in_progress"}, new_state="blocked", reason=_text(reason, "reason"))

    def retry(self, task_id: str, *, source_message: str, event_id: str, actor: str = "Hans") -> dict[str, Any]:
        return self._transition(task_id, event_key=f"{event_id}:retry", source_message=source_message,
                               actor=actor, requested="retry", allowed={"open", "blocked", "in_progress"}, new_state="in_progress")

    def report_done(self, task_id: str, *, source_message: str, event_id: str, actor: str = "Hans") -> dict[str, Any]:
        return self._transition(task_id, event_key=f"{event_id}:done", source_message=source_message,
                               actor=actor, requested="done", allowed={"open", "in_progress"}, new_state="awaiting_validation")

    def deliver_artifact(
        self, task_id: str, *, filename: str, content: bytes, source_message: str, event_id: str, actor: str = "Hans"
    ) -> dict[str, Any]:
        name = Path(_text(filename, "filename")).name
        if name != filename or name in {".", ".."}:
            raise PilotError("filename must be a simple file name; artifact was not written.")
        if not isinstance(content, (bytes, bytearray)):
            raise PilotError("content must be bytes; artifact was not written.")
        content_bytes = bytes(content)
        task = self._get(task_id)
        digest = hashlib.sha256(content_bytes).hexdigest()
        artifact_dir = self.artifact_root / task_id
        path = artifact_dir / name
        metadata = self._artifact_metadata(
            filename=name,
            path=path,
            content=content_bytes,
            sha256=digest,
            final_state="awaiting_validation",
        )
        with self._connect() as db:
            prior = db.execute(
                "SELECT * FROM events WHERE event_key=?", (f"{event_id}:artifact",)
            ).fetchone()
            if prior:
                prior_metadata = json.loads(prior["metadata_json"])
                prior_sha = prior_metadata.get("sha256")
                prior_filename = prior_metadata.get("filename")
                if (
                    prior_sha is not None
                    and prior_sha != digest
                    or prior_filename is not None
                    and prior_filename != name
                ):
                    raise PilotError("event_id was already used for a different artifact; no state changed.")
                current = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
                return self._task_result(
                    current,
                    "duplicate_artifact_delivery",
                    self._normalized_delivery_metadata(prior_metadata, current["state"]),
                )
        if task["state"] not in {"open", "in_progress"}:
            raise PilotError(f"artifact delivery requires open or in_progress state; pending action is unchanged ({task['state']}).")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=artifact_dir, delete=False) as handle:
                handle.write(content_bytes)
                temp_path = handle.name
            os.replace(temp_path, path)
            with self._connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO artifacts VALUES (?, ?, ?, ?, ?)",
                    (f"{task_id}-{digest[:12]}", task_id, str(path), digest, _utc_now()),
                )
                if not self.defer_artifact_validation:
                    db.execute(
                        "UPDATE tasks SET state='awaiting_validation', updated_at=? WHERE task_id=?",
                        (_utc_now(), task_id),
                    )
                self._event(db, event_key=f"{event_id}:artifact", source_message=source_message,
                            actor=actor, task_id=task_id, requested_transition="artifact_delivery",
                            result="staged" if self.defer_artifact_validation else "confirmed",
                            metadata=metadata)
                row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return self._task_result(
                row,
                "artifact_staged" if self.defer_artifact_validation else "artifact_confirmed",
                self._normalized_delivery_metadata(metadata, row["state"]),
            )
        finally:
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()

    def confirm_artifact_delivery(
        self, task_id: str, *, source_message: str, event_id: str, actor: str = "Hermes"
    ) -> dict[str, Any]:
        return self._transition(
            task_id,
            event_key=f"{event_id}:artifact-confirmed",
            source_message=source_message,
            actor=actor,
            requested="artifact_delivery_confirmed",
            allowed={"open", "in_progress"},
            new_state="awaiting_validation",
        )

    def deliver_text_artifact(
        self, task_id: str, *, filename: str, content_text: str, source_message: str, event_id: str, actor: str = "Hans"
    ) -> dict[str, Any]:
        if not isinstance(content_text, str):
            raise PilotError("content_text must be a UTF-8 text string; artifact was not written.")
        try:
            content = content_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise PilotError(f"content_text must be valid UTF-8 text; artifact was not written: {exc}") from exc
        return self.deliver_artifact(
            task_id,
            filename=filename,
            content=content,
            source_message=source_message,
            event_id=event_id,
            actor=actor,
        )

    def validate(
        self, task_id: str, *, approved: bool, source_message: str, event_id: str,
        reason: str | None = None, actor: str = "Hans",
    ) -> dict[str, Any]:
        if approved:
            return self._transition(task_id, event_key=f"{event_id}:validation-approved", source_message=source_message,
                                    actor=actor, requested="approve_validation", allowed={"awaiting_validation"}, new_state="done")
        return self._transition(task_id, event_key=f"{event_id}:validation-rejected", source_message=source_message,
                                actor=actor, requested="reject_validation", allowed={"awaiting_validation"}, new_state="open",
                                reason=_text(reason, "rejection reason"))

    def failure(
        self,
        task_id: str,
        *,
        action: str,
        error: str,
        source_message: str,
        event_id: str,
        actor: str = "Hermes",
        recovery_state: str | None = None,
    ) -> dict[str, Any]:
        action_value, error_value = _text(action, "action"), _text(error, "error")
        if recovery_state is not None and recovery_state not in {"open", "blocked"}:
            raise PilotError("recovery_state must be 'open' or 'blocked'")
        with self._connect() as db:
            current = self._get_row(db, task_id)
            state = recovery_state or current["state"]
            db.execute(
                "UPDATE tasks SET state=?, pending_action=?, updated_at=? WHERE task_id=?",
                (state, action_value, _utc_now(), task_id),
            )
            self._event(db, event_key=f"{event_id}:failure", source_message=source_message, actor=actor,
                        task_id=task_id, requested_transition=action_value, result="failed",
                        reason=error_value, metadata={
                            "recovery": "retry after underlying failure is resolved",
                            "state_after_failure": state,
                        })
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._task_result(row, "operation_failed", {"pending_action": action_value, "error": error_value})

    def digest(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        grouped = {state: [] for state in STATES}
        for row in rows:
            grouped[row["state"]].append({
                "task_id": row["task_id"], "owner": row["owner"], "deliverable": row["deliverable"],
                "due_date": row["due_date"], "pillar": row["pillar"], "pending_action": row["pending_action"],
            })
        return {"backend": self.backend_name, "counts": {key: len(value) for key, value in grouped.items()}, "tasks": grouped}

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM events WHERE task_id=? ORDER BY event_id", (task_id,)).fetchall()
        return [dict(row) | {"metadata": json.loads(row["metadata_json"])} for row in rows]

    def _get(self, task_id: str) -> sqlite3.Row:
        with self._connect() as db:
            return self._get_row(db, task_id)

    @staticmethod
    def _get_row(db: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise PilotError(f"unknown task {task_id}; no state changed.")
        return row

    def _sensitivity(self, task_id: str) -> str:
        return self._get(task_id)["sensitivity"]

    def _transition(self, task_id: str, *, event_key: str, source_message: str, actor: str,
                    requested: str, allowed: set[str], new_state: str,
                    reason: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._connect() as db:
            row = self._get_row(db, task_id)
            if row["state"] not in allowed:
                if db.execute("SELECT 1 FROM events WHERE event_key=?", (event_key,)).fetchone():
                    return self._task_result(row, "duplicate_transition")
                raise PilotError(f"{requested} requires state {sorted(allowed)}; current state is {row['state']}; no transition applied.")
            db.execute("UPDATE tasks SET state=?, pending_action=NULL, updated_at=? WHERE task_id=?",
                       (new_state, _utc_now(), task_id))
            self._event(db, event_key=event_key, source_message=source_message, actor=actor, task_id=task_id,
                        requested_transition=requested, result="confirmed", reason=reason, metadata=metadata)
            updated = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._task_result(updated, "transition_confirmed")

    @staticmethod
    def _artifact_metadata(
        *, filename: str, path: Path, content: bytes, sha256: str, final_state: str
    ) -> dict[str, Any]:
        return {
            "filename": filename,
            "artifact_path": str(path),
            "byte_count": len(content),
            "line_count": _line_count(content),
            "sha256": sha256,
            "final_state": final_state,
            "awaiting_validation": final_state == "awaiting_validation",
            "next_required_actor": "Hans",
            "operating_contract": (
                "After confirmed artifact delivery, report filename, byte_count, "
                "line_count, sha256, and awaiting_validation state, then stop. "
                "Do not call report_done, validate_task, terminal, or unrelated tools "
                "in the same turn."
            ),
        }

    @staticmethod
    def _normalized_delivery_metadata(metadata: dict[str, Any], state: str) -> dict[str, Any]:
        normalized = dict(metadata)
        normalized["final_state"] = state
        normalized["awaiting_validation"] = state == "awaiting_validation"
        normalized.setdefault("next_required_actor", "Hans")
        normalized.setdefault(
            "operating_contract",
            (
                "After confirmed artifact delivery, report filename, byte_count, "
                "line_count, sha256, and awaiting_validation state, then stop. "
                "Do not call report_done, validate_task, terminal, or unrelated tools "
                "in the same turn."
            ),
        )
        return normalized

    @staticmethod
    def _task_result(row: sqlite3.Row, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {
            "status": status,
            "confirmed": status in {
                "preview_ready",
                "duplicate_preview",
                "transition_confirmed",
                "duplicate_transition",
                "retry_external",
                *DELIVERY_CONFIRMED_STATUSES,
            },
            "task_id": row["task_id"], "state": row["state"], "owner": row["owner"],
            "card": json.loads(row["card_json"]), "team_message_preview": row["team_message"],
            "sensitivity": row["sensitivity"], "pending_action": row["pending_action"],
        }
        if extra:
            result.update(extra)
        return result


def default_store() -> PilotStore:
    path = os.environ.get(
        "HVE_TEAM_PILOT_DB",
        "~/.hermes/profiles/hanshermesagent/state/team-tasking-pilot.db",
    )
    return PilotStore(path)
