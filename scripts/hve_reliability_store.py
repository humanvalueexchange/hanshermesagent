#!/usr/bin/env python3
"""Durable, local-only reliability storage for deterministic Hermes watchers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMA_VERSION = 1
DEFAULT_RETENTION_DAYS = 90
DEFAULT_ESCALATE_OCCURRENCES = 3
DEFAULT_ESCALATE_AFTER_SECONDS = 3600
DEFAULT_DB = (
    Path.home()
    / ".hermes"
    / "profiles"
    / "hanshermesagent"
    / "workspace"
    / "spark-health-watchdog"
    / "reliability.db"
)
_SENSITIVE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization|cookie|session[_-]?id)"
    r"\s*[:=]\s*[^\s,;]+"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_EXCEPTION = re.compile(r"\b([A-Za-z_][\w.]*(?:Error|Exception|Failure))\b")
_IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|(?<![\w:])\[?[0-9a-fA-F:]{3,}\]?(?![\w:])")
_INTERFACE = re.compile(r"\b(?:interface|iface|device)=([A-Za-z0-9_.:-]+)", re.IGNORECASE)
_CONNECTION_AGE = re.compile(r"\b(?:connection[_ -]?age|age)=(\d+(?:\.\d+)?)s\b", re.IGNORECASE)
_SEVERITY_RANK = {"pass": 0, "warn": 1, "fail": 2}


class ReliabilityStoreError(RuntimeError):
    """Raised when reliability evidence cannot be committed."""


@dataclass(frozen=True)
class IngestionResult:
    messages: list[str]
    summaries: list[dict[str, Any]]
    recovered: list[str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def sanitize_detail(value: Any, limit: int = 500) -> str:
    """Bound and redact diagnostic text before it reaches durable storage."""
    text = _CONTROL.sub("", str(value or "")).strip()
    text = _SENSITIVE.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    def redact_url(match: re.Match[str]) -> str:
        parts = urlsplit(match.group(0))
        safe_query = [
            (key, "<redacted>" if re.search(r"token|secret|key|auth|password", key, re.I) else val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))

    text = _URL.sub(redact_url, text)
    return text[:limit]


def _extract_ip(detail: str) -> str | None:
    for candidate in _IP.findall(detail):
        candidate = candidate.strip("[]")
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _profile_subsystem(event_id: str) -> tuple[str, str]:
    parts = event_id.split(".")
    if len(parts) >= 3 and parts[0] == "profile":
        return parts[1], parts[2]
    return "spark", parts[0] if parts else "unknown"


def _event_type(item: dict[str, Any]) -> str:
    event_id = str(item.get("id", ""))
    declared = str(item.get("event_type") or "health_check")
    if ".channel." in event_id:
        return "channel_disconnect"
    if "delivery" in event_id or declared == "delivery_failure":
        return "delivery_failure"
    return declared


def _fingerprint(item: dict[str, Any]) -> str:
    key = str(item.get("fingerprint_key") or item.get("id") or "unknown")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _bool_env(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class ReliabilityStore:
    """SQLite store with one transaction per watcher cycle or review run."""

    def __init__(
        self,
        path: Path | str = DEFAULT_DB,
        *,
        retention_days: int | None = None,
        escalate_occurrences: int | None = None,
        escalate_after_seconds: int | None = None,
        triage_mode: str | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.retention_days = max(
            1,
            retention_days
            if retention_days is not None
            else int(os.environ.get("HVE_RELIABILITY_OCCURRENCE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
        )
        self.escalate_occurrences = max(
            1,
            escalate_occurrences
            if escalate_occurrences is not None
            else int(os.environ.get("HVE_WATCHDOG_ESCALATE_OCCURRENCES", DEFAULT_ESCALATE_OCCURRENCES)),
        )
        self.escalate_after_seconds = max(
            1,
            escalate_after_seconds
            if escalate_after_seconds is not None
            else int(os.environ.get("HVE_WATCHDOG_ESCALATE_AFTER_SECONDS", DEFAULT_ESCALATE_AFTER_SECONDS)),
        )
        self.triage_mode = (
            triage_mode or os.environ.get("HVE_WATCHDOG_TRIAGE_MODE", "suppress_advisories")
        ).strip().lower()
        if self.triage_mode not in {"legacy", "shadow", "suppress_advisories"}:
            raise ReliabilityStoreError("HVE_WATCHDOG_TRIAGE_MODE must be legacy, shadow, or suppress_advisories")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.db = sqlite3.connect(self.path, timeout=10)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA busy_timeout=10000")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self._initialize()
            integrity = self.db.execute("PRAGMA quick_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ReliabilityStoreError(f"reliability database integrity check failed: {integrity[0] if integrity else 'no result'}")
            os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error) as exc:
            raise ReliabilityStoreError(f"unable to open reliability database {self.path}: {exc}") from exc

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ReliabilityStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _initialize(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS reliability_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_summary (
                fingerprint TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                profile TEXT NOT NULL,
                subsystem TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                severity TEXT NOT NULL,
                impact TEXT NOT NULL,
                state TEXT NOT NULL,
                active_occurrence_count INTEGER NOT NULL DEFAULT 0,
                recovery_duration_seconds REAL,
                owner TEXT NOT NULL DEFAULT '',
                next_review_at TEXT,
                active_since TEXT,
                last_recovered_at TEXT,
                escalated_at TEXT,
                last_notified_at TEXT,
                detail TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_event_summary_review
                ON event_summary(state, last_seen DESC);
            CREATE TABLE IF NOT EXISTS event_occurrence (
                occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL REFERENCES event_summary(fingerprint),
                observed_at TEXT NOT NULL,
                sanitized_detail TEXT NOT NULL,
                exception_class TEXT,
                protocol TEXT,
                remote_ip TEXT,
                interface TEXT,
                connection_age_seconds REAL,
                recovered_at TEXT,
                UNIQUE(fingerprint, observed_at)
            );
            CREATE INDEX IF NOT EXISTS idx_event_occurrence_observed
                ON event_occurrence(observed_at DESC);
            CREATE TABLE IF NOT EXISTS review_ledger (
                review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_key TEXT NOT NULL UNIQUE,
                fingerprint TEXT NOT NULL REFERENCES event_summary(fingerprint),
                reviewed_at TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT NOT NULL,
                owner TEXT NOT NULL DEFAULT '',
                next_review_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_review_ledger_reviewed
                ON review_ledger(reviewed_at DESC);
            CREATE TABLE IF NOT EXISTS review_runs (
                period_end TEXT PRIMARY KEY,
                period_start TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                decision_count INTEGER NOT NULL
            );
            INSERT INTO reliability_meta(key, value)
                VALUES ('schema_version', '1')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value;
            """
        )
        columns = {
            row[1] for row in self.db.execute("PRAGMA table_info(event_summary)").fetchall()
        }
        if "active_occurrence_count" not in columns:
            self.db.execute(
                "ALTER TABLE event_summary ADD COLUMN active_occurrence_count INTEGER NOT NULL DEFAULT 0"
            )
        self.db.commit()

    def _finding_record(self, item: dict[str, Any], observed_at: str) -> dict[str, Any]:
        detail = sanitize_detail(item.get("detail"))
        event_id = str(item.get("id") or "unknown")
        profile, subsystem = _profile_subsystem(event_id)
        event_type = _event_type(item)
        protocol_match = re.search(r"\b(https?)\b", detail, re.IGNORECASE)
        return {
            "fingerprint": _fingerprint(item),
            "event_type": event_type,
            "profile": profile,
            "subsystem": subsystem,
            "observed_at": observed_at,
            "severity": str(item.get("severity") or "warn"),
            "impact": str(item.get("impact") or "actionable"),
            "detail": detail,
            "exception_class": (_EXCEPTION.search(detail).group(1) if _EXCEPTION.search(detail) else None),
            "protocol": protocol_match.group(1).lower() if protocol_match else None,
            "remote_ip": _extract_ip(detail),
            "interface": (_INTERFACE.search(detail).group(1) if _INTERFACE.search(detail) else None),
            "connection_age_seconds": (
                float(_CONNECTION_AGE.search(detail).group(1))
                if _CONNECTION_AGE.search(detail)
                else None
            ),
            "id": event_id,
        }

    def _should_escalate(self, record: dict[str, Any], row: sqlite3.Row, observed_at: str) -> bool:
        if record["impact"] == "none":
            return False
        if record["event_type"] in {"channel_disconnect", "delivery_failure"}:
            return True
        if int(row["occurrence_count"]) >= self.escalate_occurrences:
            return True
        if row["active_since"]:
            age = (_parse_time(observed_at) - _parse_time(row["active_since"])).total_seconds()
            if age >= self.escalate_after_seconds:
                return True
        return False

    def ingest(self, data: dict[str, Any], *, legacy_messages: Iterable[str] = ()) -> IngestionResult:
        """Ingest one watcher cycle atomically, returning only permitted notices."""
        observed_at = str(data.get("collected_at") or _iso())
        findings = data.get("findings") or []
        if not isinstance(findings, list):
            raise ReliabilityStoreError("watcher findings are not a list")
        messages: list[str] = list(legacy_messages) if self.triage_mode in {"legacy", "shadow"} else []
        summaries: list[dict[str, Any]] = []
        recovered: list[str] = []
        try:
            with self.db:
                current: set[str] = set()
                for raw_item in findings:
                    if not isinstance(raw_item, dict):
                        continue
                    record = self._finding_record(raw_item, observed_at)
                    fp = record["fingerprint"]
                    current.add(fp)
                    prior = self.db.execute(
                        "SELECT * FROM event_summary WHERE fingerprint=?", (fp,)
                    ).fetchone()
                    if prior is None:
                        self.db.execute(
                            """
                            INSERT INTO event_summary(
                                fingerprint,event_type,profile,subsystem,first_seen,last_seen,
                                occurrence_count,severity,impact,state,active_occurrence_count,active_since,detail
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                fp, record["event_type"], record["profile"], record["subsystem"],
                                observed_at, observed_at, 0, record["severity"], record["impact"],
                                "new", 0, observed_at, record["detail"],
                            ),
                        )
                        prior = self.db.execute(
                            "SELECT * FROM event_summary WHERE fingerprint=?", (fp,)
                        ).fetchone()
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO event_occurrence(
                            fingerprint,observed_at,sanitized_detail,exception_class,protocol,
                            remote_ip,interface,connection_age_seconds
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            fp, observed_at, record["detail"], record["exception_class"],
                            record["protocol"], record["remote_ip"], record["interface"],
                            record["connection_age_seconds"],
                        ),
                    )
                    inserted = self.db.execute("SELECT changes()").fetchone()[0] == 1
                    count = int(prior["occurrence_count"]) + (1 if inserted else 0)
                    active_count = (
                        (1 if inserted else 0)
                        if str(prior["state"]) in {"resolved", "wont_fix"}
                        else int(prior["active_occurrence_count"]) + (1 if inserted else 0)
                    )
                    state = "monitoring" if active_count else str(prior["state"])
                    if self._should_escalate(
                        {**record, "occurrence_count": active_count},
                        {
                            **dict(prior),
                            "occurrence_count": active_count,
                            "active_since": (
                                observed_at
                                if str(prior["state"]) in {"resolved", "wont_fix"}
                                else prior["active_since"]
                            ),
                        },
                        observed_at,
                    ):
                        state = "escalated"
                    self.db.execute(
                        """
                        UPDATE event_summary
                        SET event_type=?,profile=?,subsystem=?,last_seen=?,occurrence_count=?,
                            severity=?,impact=?,state=?,active_occurrence_count=?,active_since=?,detail=?
                        WHERE fingerprint=?
                        """,
                        (
                            record["event_type"], record["profile"], record["subsystem"], observed_at,
                            count, record["severity"], record["impact"], state, active_count,
                            observed_at if str(prior["state"]) in {"resolved", "wont_fix"} else prior["active_since"],
                            record["detail"], fp,
                        ),
                    )
                    updated = self.db.execute(
                        "SELECT * FROM event_summary WHERE fingerprint=?", (fp,)
                    ).fetchone()
                    assert updated is not None
                    previous_state = str(prior["state"])
                    if state == "escalated" and previous_state != "escalated":
                        self.db.execute(
                            """
                            UPDATE event_summary
                            SET escalated_at=COALESCE(escalated_at,?), last_notified_at=?
                            WHERE fingerprint=?
                            """,
                            (observed_at, observed_at, fp),
                        )
                        label = record["severity"].upper()
                        messages.append(f"ESCALATED {label} {record['id']}: {record['detail']}")
                    elif self.triage_mode in {"legacy", "shadow"} and previous_state == state:
                        pass
                    summaries.append(dict(updated))

                active_rows = self.db.execute(
                    "SELECT * FROM event_summary WHERE state IN ('new','monitoring','escalated')"
                ).fetchall()
                for row in active_rows:
                    fp = str(row["fingerprint"])
                    if fp in current:
                        continue
                    last_occurrence = self.db.execute(
                        """
                        SELECT occurrence_id,observed_at FROM event_occurrence
                        WHERE fingerprint=? AND recovered_at IS NULL
                        ORDER BY observed_at DESC LIMIT 1
                        """,
                        (fp,),
                    ).fetchone()
                    if last_occurrence is None:
                        continue
                    self.db.execute(
                        "UPDATE event_occurrence SET recovered_at=? WHERE occurrence_id=?",
                        (observed_at, last_occurrence["occurrence_id"]),
                    )
                    duration = max(
                        0.0,
                        (_parse_time(observed_at) - _parse_time(row["active_since"] or row["first_seen"])).total_seconds(),
                    )
                    self.db.execute(
                        """
                        UPDATE event_summary
                        SET state='resolved',active_occurrence_count=0,last_recovered_at=?,recovery_duration_seconds=?
                        WHERE fingerprint=?
                        """,
                        (observed_at, duration, fp),
                    )
                    recovered.append(fp)
                    if str(row["state"]) == "escalated":
                        label = str(row["severity"]).upper()
                        messages.append(f"RECOVERY {label} {row['event_type']} ({row['profile']}/{row['subsystem']})")

                cutoff = _iso(_utc_now() - timedelta(days=self.retention_days))
                self.db.execute("DELETE FROM event_occurrence WHERE observed_at < ?", (cutoff,))
        except sqlite3.Error as exc:
            raise ReliabilityStoreError(f"reliability ingestion rolled back: {exc}") from exc
        return IngestionResult(messages=messages, summaries=summaries, recovered=recovered)

    def review(
        self,
        period_start: str,
        period_end: str,
        *,
        reviewer: str = "hermes-no-agent",
        now: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate and record a bounded weekly decision queue idempotently."""
        reviewed_at = now or _iso()
        try:
            with self.db:
                existing = self.db.execute(
                    "SELECT * FROM review_runs WHERE period_end=?", (period_end,)
                ).fetchone()
                if existing is not None:
                    rows = self.db.execute(
                        "SELECT * FROM review_ledger WHERE review_key LIKE ? ORDER BY review_id",
                        (f"%:{period_end}",),
                    ).fetchall()
                    return {"period_start": period_start, "period_end": period_end, "decisions": [dict(r) for r in rows], "idempotent": True}
                rows = self.db.execute(
                    """
                    SELECT * FROM event_summary
                    WHERE (last_seen >= ? AND last_seen < ?)
                       OR (last_recovered_at >= ? AND last_recovered_at < ?)
                    ORDER BY
                        CASE state WHEN 'escalated' THEN 0 WHEN 'monitoring' THEN 1 ELSE 2 END,
                        CASE severity WHEN 'fail' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,
                        occurrence_count DESC, last_seen DESC
                    LIMIT 100
                    """,
                    (period_start, period_end, period_start, period_end),
                ).fetchall()
                decisions: list[dict[str, Any]] = []
                next_review = _iso(_parse_time(period_end) + timedelta(days=7))
                for row in rows:
                    state = str(row["state"])
                    if state == "escalated":
                        decision = "escalate"
                        rationale = "Sustained or immediate-impact event remains escalated."
                    elif state == "resolved":
                        decision = "resolved"
                        rationale = "Event recovered; retain evidence and monitor for recurrence."
                    elif int(row["occurrence_count"]) >= self.escalate_occurrences:
                        decision = "investigate"
                        rationale = "Repeated monitoring event crossed the review frequency threshold."
                    else:
                        decision = "continue_monitoring"
                        rationale = "No sustained impact threshold met; retain for trend review."
                    key = f"{row['fingerprint']}:{period_end}"
                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO review_ledger(
                            review_key,fingerprint,reviewed_at,reviewer,decision,rationale,owner,next_review_at
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            key, row["fingerprint"], reviewed_at, reviewer, decision, rationale,
                            row["owner"], None if decision == "resolved" else next_review,
                        ),
                    )
                    decisions.append(
                        {
                            "fingerprint": row["fingerprint"],
                            "event_type": row["event_type"],
                            "profile": row["profile"],
                            "subsystem": row["subsystem"],
                            "severity": row["severity"],
                            "impact": row["impact"],
                            "state": row["state"],
                            "occurrence_count": row["occurrence_count"],
                            "decision": decision,
                            "rationale": rationale,
                        }
                    )
                self.db.execute(
                    """
                    INSERT INTO review_runs(period_end,period_start,reviewed_at,reviewer,decision_count)
                    VALUES(?,?,?,?,?)
                    """,
                    (period_end, period_start, reviewed_at, reviewer, len(decisions)),
                )
        except sqlite3.Error as exc:
            raise ReliabilityStoreError(f"reliability review rolled back: {exc}") from exc
        return {"period_start": period_start, "period_end": period_end, "decisions": decisions, "idempotent": False}


def default_db_path() -> Path:
    return Path(os.environ.get("HVE_RELIABILITY_DB", str(DEFAULT_DB)))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReliabilityStoreError(f"unable to read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReliabilityStoreError(f"{path} is not a JSON object")
    return value
