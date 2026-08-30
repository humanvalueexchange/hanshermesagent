#!/usr/bin/env python3
"""Build a read-only evidence manifest for the HVE weekly mission review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("America/Toronto")
PROFILE_ROOT = Path.home() / ".hermes" / "profiles" / "hanshermesagent"
CRON_ROOT = PROFILE_ROOT / "cron"
JOBS_PATH = CRON_ROOT / "jobs.json"
CRON_EXECUTIONS_PATH = CRON_ROOT / "executions.db"
LIBRARY_MANIFEST_ROOT = Path("/hve-library/state/manifests")
STATE_DB_PATH = PROFILE_ROOT / "state.db"
SESSION_INDEX_PATH = PROFILE_ROOT / "sessions" / "sessions.json"
GMAIL_JOB_ID = "97f6606e2a4d"
HEALTH_WATCHDOG_JOB_ID = "292f7c4b22eb"
SKILL_JOB_NAMES = {"hve-daily-skill-recommendation", "hve-weekly-skill-review"}
SKILL_SCOPE_METADATA = {
    "hve-daily-skill-recommendation": {
        "product_scope": "HVE-LIFE-OS",
        "capability_areas": [
            "Five Wealth measurement",
            "client intake and assessment",
            "offer delivery",
            "managed-service improvement",
        ],
        "evidence_rule": "A recommendation is not progress unless tied to a tested or delivered product capability.",
    },
    "hve-weekly-skill-review": {
        "product_scope": "HVE-LIFE-OS",
        "capability_areas": [
            "product capability readiness",
            "offer-ladder deliverables",
            "client outcomes",
            "managed-service monitoring",
        ],
        "evidence_rule": "Count only evidence tied to an HVE-LIFE-OS capability, offer, deliverable, or client outcome.",
    },
}
TELEGRAM_SOURCE_TYPES = {"web_link", "pdf_document"}
DATE_IN_FILENAME = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})[_-](?P<time>\d{2}[-:]\d{2}[-:]\d{2})")


def parse_local_date(value: str) -> date:
    return date.fromisoformat(value)


def period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start:
        raise ValueError("period end must not precede period start")
    start_dt = datetime.combine(start, time.min, LOCAL_TZ)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, LOCAL_TZ)
    return start_dt, end_dt


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def epoch_bounds(start_dt: datetime, end_dt: datetime) -> tuple[float, float]:
    return start_dt.timestamp(), end_dt.timestamp()


def in_period(value: datetime, start_dt: datetime, end_dt: datetime) -> bool:
    return start_dt <= value < end_dt


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_json_payload(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(re.findall(r"(\{\s*\"source\"\s*:\s*\"gmail\".*?\})", text, flags=re.DOTALL))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("source") == "gmail":
            return parsed
    return None


def artifact_datetime(path: Path) -> datetime | None:
    match = DATE_IN_FILENAME.search(path.name)
    if not match:
        return datetime.fromtimestamp(path.stat().st_mtime, LOCAL_TZ)
    stamp = f"{match.group('date')}T{match.group('time').replace('-', ':')}"
    return datetime.fromisoformat(stamp).replace(tzinfo=LOCAL_TZ)


def load_jobs() -> list[dict[str, Any]]:
    if not JOBS_PATH.is_file():
        return []
    data = json.loads(JOBS_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def job_scope(job: dict[str, Any]) -> str:
    name = str(job.get("name", ""))
    if job.get("id") == HEALTH_WATCHDOG_JOB_ID:
        return "excluded_infrastructure_health"
    if name in SKILL_JOB_NAMES:
        prompt = str(job.get("prompt", ""))
        return "hve_life_os_required_retarget" if "HVE-LIFE-OS" not in prompt else "hve_life_os"
    if name == "gmail-daily-hans-memory":
        return "hve_gmail_intelligence"
    if name == "twin-morning-brief-local-qwen-6am-EST":
        return "hve_daily_operating_brief"
    if name.startswith("hve-"):
        return "hve_life_os_review_required"
    return "unclassified"


def collect_gmail(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    job_dir = CRON_ROOT / "output" / GMAIL_JOB_ID
    expected_dates = [
        (start_dt.date() + timedelta(days=offset)).isoformat()
        for offset in range((end_dt.date() - start_dt.date()).days)
    ]
    artifacts: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    if job_dir.is_dir():
        for path in sorted(job_dir.iterdir()):
            if not path.is_file() or path.suffix not in {".md", ".json", ".txt"}:
                continue
            payload = parse_json_payload(path) if path.suffix != ".json" else None
            if path.suffix == ".json":
                try:
                    candidate = json.loads(path.read_text(encoding="utf-8"))
                    payload = candidate if candidate.get("source") == "gmail" else None
                except (OSError, json.JSONDecodeError):
                    payload = None
            target_date = payload.get("target_date") if payload else None
            if target_date not in expected_dates:
                continue
            artifacts.append(
                {
                    "path": str(path),
                    "target_date": target_date,
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
            if payload:
                bundles.append(payload)

    messages: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        for message in bundle.get("messages", []):
            message_id = str(message.get("id") or message.get("message_id") or "")
            if not message_id:
                continue
            messages[message_id] = {
                "record_id": f"gmail:{message_id}",
                "source_type": "gmail",
                "channel_scope": "mailbox",
                "event_at": message.get("date"),
                "title": message.get("subject") or "(no subject)",
                "summary": "Daily Gmail intelligence record; source body is not copied into this manifest.",
                "evidence_class": "signal",
                "verification_state": "verified",
                "provenance": {
                    "message_id": message_id,
                    "header_message_id": message.get("message_id"),
                    "artifact_paths": [
                        item["path"] for item in artifacts if item["target_date"] == bundle.get("target_date")
                    ],
                },
                "confidence": "high",
                "sensitivity": "confidential",
                "data_handling_state": "metadata_only",
            }

    covered_dates = sorted({item["target_date"] for item in artifacts})
    missing_dates = sorted(set(expected_dates) - set(covered_dates))
    return {
        "status": "ok" if not missing_dates else "partial",
        "collection_mode": "read_only_daily_bundle_aggregation",
        "job_id": GMAIL_JOB_ID,
        "expected_dates": expected_dates,
        "covered_dates": covered_dates,
        "missing_dates": missing_dates,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "message_count": len(messages),
        "records": list(messages.values()),
        "warnings": [
            "Daily Gmail bundles are capped by the existing collector; coverage must be audited for truncation.",
            "The current collector filters messages from hans@hveglobal.ca in the Gmail INBOX.",
        ],
    }


def collect_telegram(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    invalid_manifests = 0
    if LIBRARY_MANIFEST_ROOT.is_dir():
        for path in LIBRARY_MANIFEST_ROOT.glob("*.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                invalid_manifests += 1
                continue
            if not isinstance(manifest, dict) or manifest.get("source_type") not in TELEGRAM_SOURCE_TYPES:
                continue
            captures = manifest.get("captures", [])
            recent = []
            for capture in captures if isinstance(captures, list) else []:
                try:
                    captured_at = datetime.fromisoformat(
                        str(capture.get("captured_at")).replace("Z", "+00:00")
                    )
                except (TypeError, ValueError):
                    continue
                if in_period(captured_at, start_dt, end_dt):
                    recent.append(capture)
            if not recent:
                continue
            document_id = str(manifest.get("document_id") or path.stem)
            latest = max(recent, key=lambda item: str(item.get("captured_at", "")))
            records[document_id] = {
                "record_id": f"telegram:{document_id}",
                "source_type": "telegram",
                "channel_scope": "channel",
                "title": manifest.get("title") or document_id,
                "summary": "Archived Telegram link/document; extracted text is reviewed later by the synthesis stage.",
                "evidence_class": "signal",
                "verification_state": "verified",
                "provenance": {
                    "document_id": document_id,
                    "manifest_path": str(path),
                    "canonical_url": manifest.get("canonical_url"),
                    "capture_context": [item.get("capture_context") for item in recent],
                    "captures_in_period": len(recent),
                    "latest_capture_at": latest.get("captured_at"),
                },
                "indexed": manifest.get("status") == "indexed",
                "extracted_text_available": bool(manifest.get("extracted_text_path")),
                "confidence": "high",
                "sensitivity": "internal",
                "data_handling_state": "included_summary",
            }
    return {
        "status": "ok" if invalid_manifests == 0 else "partial",
        "manifest_root": str(LIBRARY_MANIFEST_ROOT),
        "record_count": len(records),
        "records": list(records.values()),
        "known_coverage_gap": "Telegram conversational messages are not included; only archived web links and PDF documents are inventoried.",
        "invalid_manifest_count": invalid_manifests,
    }


def load_configured_routes() -> list[dict[str, Any]]:
    if not SESSION_INDEX_PATH.is_file():
        return []
    data = json.loads(SESSION_INDEX_PATH.read_text(encoding="utf-8"))
    routes = []
    for entry in data.values():
        if not isinstance(entry, dict) or entry.get("platform") != "whatsapp":
            continue
        session_key = str(entry.get("session_key", ""))
        if not session_key.startswith("agent:hanshermesagent:"):
            continue
        origin = entry.get("origin") or {}
        routes.append(
            {
                "configured_scope_id": origin.get("chat_id"),
                "channel_scope": "group" if entry.get("chat_type") == "group" else "dm",
                "display_name": origin.get("chat_name") or entry.get("display_name"),
                "profile": session_key.split(":")[1],
                "session_id": entry.get("session_id"),
            }
        )
    unique: dict[tuple[Any, Any], dict[str, Any]] = {}
    for route in routes:
        unique[(route["configured_scope_id"], route["channel_scope"])] = route
    return list(unique.values())


def collect_sessions(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    start_epoch, end_epoch = epoch_bounds(start_dt, end_dt)
    routes = load_configured_routes()
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not STATE_DB_PATH.is_file():
        warnings.append("Hermes state database is unavailable; session activity cannot be queried.")
    else:
        with sqlite3.connect(STATE_DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            query = """
                SELECT s.id, s.source, s.profile_name, s.session_key, s.chat_id,
                       s.chat_type, s.display_name, s.started_at, s.ended_at,
                       s.last_activity_at, COUNT(m.id) AS message_count
                FROM sessions AS s
                LEFT JOIN messages AS m
                  ON m.session_id = s.id
                 AND m.timestamp >= ?
                 AND m.timestamp < ?
                WHERE (s.chat_type IN ('dm', 'group')
                       OR s.session_key LIKE '%:whatsapp:%')
                  AND s.profile_name = 'hanshermesagent'
                  AND (s.started_at < ? OR s.started_at IS NULL)
                GROUP BY s.id
                ORDER BY COALESCE(s.last_activity_at, s.started_at) ASC
            """
            for row in connection.execute(query, (start_epoch, end_epoch, end_epoch)):
                scope = "group" if row["chat_type"] == "group" else "dm"
                records.append(
                    {
                        "record_id": f"session:{row['id']}",
                        "source_type": "whatsapp" if ":whatsapp:" in str(row["session_key"]) else "session",
                        "channel_scope": scope,
                        "configured_scope_id": row["chat_id"],
                        "title": row["display_name"] or row["session_key"] or row["id"],
                        "summary": "Session metadata and message count; message bodies are not copied into this manifest.",
                        "evidence_class": "signal",
                        "verification_state": "verified",
                        "provenance": {
                            "session_id": row["id"],
                            "session_key": row["session_key"],
                            "profile": row["profile_name"],
                            "started_at": row["started_at"],
                            "ended_at": row["ended_at"],
                            "last_activity_at": row["last_activity_at"],
                            "messages_in_period": row["message_count"],
                        },
                        "confidence": "high",
                        "sensitivity": "confidential",
                        "data_handling_state": "metadata_only",
                    }
                )
    configured_keys = {(item["configured_scope_id"], item["channel_scope"]) for item in routes}
    observed_keys = {
        (item.get("configured_scope_id"), item["channel_scope"])
        for item in records
        if item["provenance"]["messages_in_period"] > 0
    }
    for route in routes:
        route["activity_state"] = "observed" if (
            route["configured_scope_id"], route["channel_scope"]
        ) in observed_keys else "no_activity_or_unavailable"
    if not records:
        warnings.append("No WhatsApp/session message records were returned for the period; route inventory is still retained.")
    return {
        "status": "ok" if not warnings else "partial",
        "configured_routes": routes,
        "route_count": len(configured_keys),
        "record_count": len(records),
        "records": records,
        "warnings": warnings,
    }


def collect_cron(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    jobs = load_jobs()
    in_scope_jobs: list[dict[str, Any]] = []
    excluded_jobs: list[dict[str, Any]] = []
    for job in jobs:
        scope = job_scope(job)
        item = {
            "job_id": job.get("id"),
            "name": job.get("name"),
            "schedule": job.get("schedule_display") or job.get("schedule"),
            "enabled": job.get("enabled", True),
            "model": job.get("model") or job.get("model_snapshot"),
            "deliver": job.get("deliver"),
            "scope": scope,
        }
        if item["name"] in SKILL_SCOPE_METADATA:
            item.update(SKILL_SCOPE_METADATA[item["name"]])
            item["scope_status"] = scope
        (excluded_jobs if scope == "excluded_infrastructure_health" else in_scope_jobs).append(item)

    executions: list[dict[str, Any]] = []
    if CRON_EXECUTIONS_PATH.is_file():
        with sqlite3.connect(CRON_EXECUTIONS_PATH) as connection:
            connection.row_factory = sqlite3.Row
            query = """
                SELECT id, job_id, source, status, claimed_at, started_at, finished_at, error
                FROM executions
                WHERE COALESCE(started_at, claimed_at) < ?
                  AND COALESCE(finished_at, started_at, claimed_at) >= ?
            """
            for row in connection.execute(query, (iso_utc(end_dt), iso_utc(start_dt))):
                if str(row["job_id"]) == HEALTH_WATCHDOG_JOB_ID:
                    continue
                executions.append(dict(row))
    else:
        executions.append({"status": "unavailable", "error": "Cron execution database is missing."})

    artifacts: list[dict[str, Any]] = []
    output_root = CRON_ROOT / "output"
    for job in in_scope_jobs:
        job_dir = output_root / str(job["job_id"])
        if not job_dir.is_dir():
            continue
        for path in job_dir.iterdir():
            if not path.is_file():
                continue
            timestamp = artifact_datetime(path)
            if timestamp and in_period(timestamp, start_dt, end_dt):
                artifacts.append(
                    {
                        "job_id": job["job_id"],
                        "job_name": job["name"],
                        "path": str(path),
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                        "artifact_at": timestamp.isoformat(),
                    }
                )
    return {
        "status": "ok" if CRON_EXECUTIONS_PATH.is_file() else "partial",
        "in_scope_jobs": in_scope_jobs,
        "excluded_jobs": excluded_jobs,
        "execution_count": len(executions),
        "executions": executions,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "warnings": [
            "Execution records do not contain artifact paths or delivery receipts; those are joined from job output files and job metadata.",
            "Skills jobs require HVE-LIFE-OS-specific prompts before their outputs count as product progress.",
        ],
    }


def build_manifest(start: date, end: date) -> dict[str, Any]:
    start_dt, end_dt = period_bounds(start, end)
    return {
        "schema": "hve-weekly-mission-source-manifest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reporting_period": {
            "timezone": "America/Toronto",
            "start_local": start_dt.isoformat(),
            "end_local_exclusive": end_dt.isoformat(),
            "start_utc": iso_utc(start_dt),
            "end_utc_exclusive": iso_utc(end_dt),
        },
        "governance": {
            "read_only": True,
            "raw_message_bodies_included": False,
            "telegram_conversation_included": False,
            "health_watchdog_included": False,
        },
        "sources": {
            "gmail": collect_gmail(start_dt, end_dt),
            "telegram": collect_telegram(start_dt, end_dt),
            "whatsapp_sessions": collect_sessions(start_dt, end_dt),
            "cron": collect_cron(start_dt, end_dt),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="Local reporting start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Local reporting end date, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(parse_local_date(args.start), parse_local_date(args.end))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
