#!/usr/bin/env python3
"""Deterministic, no-agent HVE DGX Spark health watcher.

The scheduler delivers this script's stdout directly. Healthy cycles are silent;
state and evidence remain under the hanshermesagent runtime profile.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hve_reliability_store import ReliabilityStore, ReliabilityStoreError

_configured_hermes_home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
if _configured_hermes_home.name == "hanshermesagent" and _configured_hermes_home.parent.name == "profiles":
    HERMES_HOME = _configured_hermes_home.parent.parent
else:
    HERMES_HOME = _configured_hermes_home
PROFILE_HOME = HERMES_HOME / "profiles" / "hanshermesagent"
HVE_AGENT_ROOT = Path(os.environ.get("HVE_AGENT_ROOT", str(Path.home() / "hanshermesagent")))
HVE_KNOWLEDGE_ROOT = Path(os.environ.get("HVE_KNOWLEDGE_ROOT", str(Path.home() / ".hve-knowledge")))
DEFAULT_STATE = PROFILE_HOME / "workspace" / "spark-health-watchdog" / "alert-state.json"
DEFAULT_EVIDENCE = PROFILE_HOME / "workspace" / "spark-health-watchdog" / "evidence"
DEFAULT_RELIABILITY_DB = PROFILE_HOME / "workspace" / "spark-health-watchdog" / "reliability.db"
JOBS_PATH = PROFILE_HOME / "cron" / "jobs.json"
OLLAMA_BASE = os.environ.get("OLLAMA_HEALTH_URL", "http://127.0.0.1:11434")
ALERT_ROUTE = os.environ.get("HVE_WATCHDOG_ALERT_ROUTE", "whatsapp:<configured-Hans-destination>")
STALE_METADATA_SECONDS = 2 * 60 * 60
RECENT_ERROR_WINDOW = "-30 min"
NONCRITICAL_CRON_FAILURE_THRESHOLD = 3
CRITICAL_CRON_JOBS = {
    name.strip()
    for name in os.environ.get("HVE_CRITICAL_CRON_JOBS", "").split(",")
    if name.strip()
}

# This is the only profile registry used by the watcher. Retired collector/default
# profiles are intentionally absent and therefore cannot affect health calculations.
PROFILE_REGISTRY: dict[str, dict[str, Any]] = {
    "hanshermesagent": {
        "lifecycle": "active",
        "service": "hermes-gateway-hanshermesagent.service",
        "config": PROFILE_HOME / "config.yaml",
        "profile": PROFILE_HOME / "profile.yaml",
        "gateway_state": PROFILE_HOME / "gateway_state.json",
        "gateway_pid": PROFILE_HOME / "gateway.pid",
        "required_channels": ("whatsapp",),
        "disabled_channels": ("telegram",),
        "process_marker": "--profile hanshermesagent gateway run",
        "required_files": (),
        "databases": (PROFILE_HOME / "state.db", PROFILE_HOME / "cron" / "executions.db"),
    },
    "hve-librarian": {
        "lifecycle": "active",
        "service": "hermes-gateway-hve-librarian.service",
        "config": HERMES_HOME / "profiles" / "hve-librarian" / "config.yaml",
        "profile": HERMES_HOME / "profiles" / "hve-librarian" / "profile.yaml",
        "gateway_state": HERMES_HOME / "profiles" / "hve-librarian" / "gateway_state.json",
        "gateway_pid": HERMES_HOME / "profiles" / "hve-librarian" / "gateway.pid",
        "required_channels": ("telegram",),
        "disabled_channels": ("whatsapp",),
        "process_marker": "--profile hve-librarian gateway run",
        "required_files": (
            HVE_AGENT_ROOT / "mcp" / "link_collector_server.py",
            Path("/opt/hve-knowledge-layer/current/src"),
            HVE_KNOWLEDGE_ROOT / "venv" / "bin" / "python3",
        ),
        "databases": (
            HERMES_HOME / "profiles" / "hve-librarian" / "state.db",
            HERMES_HOME / "profiles" / "hve-librarian" / "cron" / "executions.db",
        ),
    },
    "hermes-coder": {
        "lifecycle": "active",
        "service": "hermes-coder-worker.service",
        "config": HERMES_HOME / "profiles" / "hermes-coder" / "config.yaml",
        "profile": HERMES_HOME / "profiles" / "hermes-coder" / "profile.yaml",
        "required_channels": (),
        "disabled_channels": (),
        "process_marker": str(HERMES_HOME / "profiles" / "hermes-coder" / "worker.py"),
        "required_files": (
            HERMES_HOME / "profiles" / "hermes-coder" / "worker.py",
            HERMES_HOME / "profiles" / "hermes-coder" / "coder_queue.py",
        ),
        "databases": (HERMES_HOME / "profiles" / "hermes-coder" / "coder-queue.sqlite3",),
        "queue_db": HERMES_HOME / "profiles" / "hermes-coder" / "coder-queue.sqlite3",
    },
    "hve-alpha": {
        "lifecycle": "planned/standby",
        "service": None,
        "config": HERMES_HOME / "profiles" / "hve-alpha" / "config.yaml",
        "profile": HERMES_HOME / "profiles" / "hve-alpha" / "profile.yaml",
        "required_channels": (),
        "disabled_channels": (),
        "process_marker": None,
        "required_files": (),
        "databases": (HERMES_HOME / "profiles" / "hve-alpha" / "state.db", HERMES_HOME / "profiles" / "hve-alpha" / "cron" / "executions.db"),
    },
    "hve-cfo": {
        "lifecycle": "planned/standby",
        "service": None,
        "config": HERMES_HOME / "profiles" / "hve-cfo" / "config.yaml",
        "profile": HERMES_HOME / "profiles" / "hve-cfo" / "profile.yaml",
        "gateway_state": HERMES_HOME / "profiles" / "hve-cfo" / "gateway_state.json",
        "required_channels": (),
        "disabled_channels": (),
        "process_marker": None,
        "required_files": (),
        "databases": (HERMES_HOME / "profiles" / "hve-cfo" / "state.db", HERMES_HOME / "profiles" / "hve-cfo" / "cron" / "executions.db"),
    },
}

OLLAMA_WORKLOADS: dict[str, dict[str, Any]] = {
    "qwen3.8-hermes:27b-128k": {"context": 131072, "workloads": ("Hermes active profiles", "Hermes-Coder")},
    "qwen3.8-distill-2b:q4_k_m": {"context": 32768, "workloads": ("local extraction and auxiliary workloads",)},
    "nomic-embed-text:latest": {"context": 2048, "workloads": ("embedding workloads",)},
}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).isoformat(timespec="seconds")


def run_cmd(command: list[str], timeout: int = 8) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {"ok": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def add_check(
    checks: dict[str, Any],
    findings: list[dict[str, Any]],
    name: str,
    status: str,
    detail: str,
    *,
    event_type: str = "health_check",
    impact: str | None = None,
    fingerprint_key: str | None = None,
    **data: Any,
) -> None:
    checks[name] = {
        "status": status,
        "detail": detail,
        "event_type": event_type,
        "impact": impact or ("actionable" if status in {"warn", "fail"} else "none"),
        **data,
    }
    if status in {"warn", "fail"}:
        findings.append(
            {
                "id": name,
                "severity": status,
                "detail": detail,
                "event_type": event_type,
                "impact": impact or ("actionable" if status in {"warn", "fail"} else "none"),
                "fingerprint_key": fingerprint_key or name,
            }
        )


def process_cmdline(pid: int) -> str | None:
    path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()


def pid_alive(pid: int) -> bool:
    return pid > 0 and Path(f"/proc/{pid}").exists()


def systemd_active(unit: str) -> tuple[bool, str, int | None]:
    active = run_cmd(["systemctl", "--user", "is-active", "--quiet", unit], timeout=6)
    show = run_cmd(["systemctl", "--user", "show", unit, "--property=MainPID", "--value"], timeout=6)
    pid: int | None = None
    if show["ok"] and show["stdout"].isdigit():
        pid = int(show["stdout"])
    return active["ok"], active["stderr"] or active["stdout"] or "inactive", pid


def parse_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields and fields[0].isdigit():
                values[key] = int(fields[0]) * (1024 if len(fields) > 1 and fields[1] == "kB" else 1)
    except (OSError, UnicodeError, ValueError):
        return {}
    return values


def check_host(checks: dict[str, Any], findings: list[dict[str, str]]) -> None:
    uptime = "unknown"
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
        uptime = f"{uptime_seconds / 86400:.1f}d"
    except (OSError, ValueError, IndexError):
        add_check(checks, findings, "host.uptime", "warn", "unable to read /proc/uptime")
    load = os.getloadavg()
    cpu_count = os.cpu_count() or 1
    load_status = "warn" if load[0] > cpu_count * 1.5 else "pass"
    add_check(checks, findings, "host.cpu_load", load_status, f"load1={load[0]:.2f} cores={cpu_count}", load=load)
    mem = parse_meminfo()
    if not mem:
        add_check(checks, findings, "host.memory", "fail", "unable to read /proc/meminfo")
    else:
        avail = mem.get("MemAvailable", 0)
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = max(0, swap_total - swap_free)
        mem_status = "warn" if avail < 4 * 1024**3 or (swap_total and swap_used > swap_total * 0.5) else "pass"
        add_check(checks, findings, "host.memory", mem_status, f"available={avail // 1024**2}MiB swap_used={swap_used // 1024**2}MiB", available_bytes=avail, swap_used_bytes=swap_used)
    add_check(checks, findings, "host.identity", "pass", f"hostname={socket.gethostname()} uptime={uptime}")

    gpu = run_cmd(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"], timeout=10)
    if not gpu["ok"] or not gpu["stdout"]:
        add_check(checks, findings, "host.gpu", "fail", gpu["stderr"] or gpu["stdout"] or "nvidia-smi returned no GPU")
    else:
        add_check(checks, findings, "host.gpu", "pass", gpu["stdout"].splitlines()[0])

    disk = shutil.disk_usage("/")
    disk_percent = disk.used / disk.total * 100
    disk_status = "fail" if disk_percent >= 95 else "warn" if disk_percent >= 85 else "pass"
    add_check(checks, findings, "host.disk", disk_status, f"root={disk_percent:.1f}% used free={disk.free // 1024**3}GiB")
    inode = run_cmd(["df", "-Pi", "/"], timeout=6)
    if inode["ok"] and len(inode["stdout"].splitlines()) >= 2:
        fields = inode["stdout"].splitlines()[-1].split()
        inode_pct = int(fields[4].rstrip("%")) if len(fields) > 4 and fields[4].rstrip("%").isdigit() else None
        inode_status = "fail" if inode_pct is not None and inode_pct >= 95 else "warn" if inode_pct is not None and inode_pct >= 85 else "pass"
        add_check(checks, findings, "host.inodes", inode_status, f"root={inode_pct}% used" if inode_pct is not None else "inode usage unavailable")
    else:
        add_check(checks, findings, "host.inodes", "warn", inode["stderr"] or "df inode probe failed")

    failed = run_cmd(["systemctl", "--user", "--failed", "--no-legend", "--no-pager"], timeout=8)
    failed_units = [line.split()[0] for line in failed["stdout"].splitlines() if line.strip()] if failed["ok"] else []
    add_check(checks, findings, "host.failed_user_services", "warn" if failed_units else "pass", ", ".join(failed_units[:8]) if failed_units else "none")


def url_json(path: str, timeout: int = 8) -> tuple[dict[str, Any] | None, str | None]:
    request = urllib.request.Request(f"{OLLAMA_BASE}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, str(exc)


def check_ollama(checks: dict[str, Any], findings: list[dict[str, str]]) -> None:
    version, error = url_json("/api/version")
    if error or not isinstance(version, dict):
        add_check(checks, findings, "ollama.api", "fail", error or "invalid /api/version response")
        return
    add_check(checks, findings, "ollama.api", "pass", f"version={version.get('version', 'unknown')}")
    tags, error = url_json("/api/tags")
    if error or not isinstance(tags, dict):
        add_check(checks, findings, "ollama.models.installed", "fail", error or "invalid /api/tags response")
        return
    installed = {str(item.get("name")) for item in tags.get("models", []) if isinstance(item, dict)}
    missing = sorted(set(OLLAMA_WORKLOADS) - installed)
    add_check(checks, findings, "ollama.models.installed", "fail" if missing else "pass", f"missing={', '.join(missing)}" if missing else f"installed={len(OLLAMA_WORKLOADS)} required models")
    ps, error = url_json("/api/ps")
    if error or not isinstance(ps, dict):
        add_check(checks, findings, "ollama.models.hot", "fail", error or "invalid /api/ps response")
        return
    running = {str(item.get("name")): item for item in ps.get("models", []) if isinstance(item, dict)}
    hot_missing = sorted(set(OLLAMA_WORKLOADS) - set(running))
    add_check(checks, findings, "ollama.models.hot", "warn" if hot_missing else "pass", f"not hot={', '.join(hot_missing)}" if hot_missing else "all required workloads hot")
    for name, declaration in OLLAMA_WORKLOADS.items():
        item = running.get(name)
        if item is None:
            add_check(checks, findings, f"ollama.placement.{name}", "not_applicable", "model not hot")
            continue
        context = item.get("context_length")
        processor = str(item.get("processor", ""))
        if not processor:
            size = item.get("size")
            size_vram = item.get("size_vram")
            if isinstance(size, int) and isinstance(size_vram, int):
                processor = "100% GPU" if size_vram >= size else f"{size_vram / size * 100:.0f}% GPU / CPU"
            else:
                processor = "unknown"
        context_status = "pass" if context == declaration["context"] else "warn"
        add_check(checks, findings, f"ollama.context.{name}", context_status, f"context={context} expected={declaration['context']}")
        placement_status = "pass" if "GPU" in processor.upper() and "CPU" not in processor.upper() else "warn"
        add_check(checks, findings, f"ollama.placement.{name}", placement_status, f"processor={processor}")


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    return value if isinstance(value, dict) else None, None


def metadata_age(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return (now() - parsed).total_seconds()


def check_sqlite(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "not_applicable", "database absent"
    try:
        uri = f"file:{path}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            result = db.execute("PRAGMA quick_check").fetchone()
    except (sqlite3.Error, OSError) as exc:
        return "fail", str(exc)
    if not result or result[0] != "ok":
        return "fail", str(result[0] if result else "no quick_check result")
    return "pass", "quick_check=ok"


def check_profile(name: str, spec: dict[str, Any], checks: dict[str, Any], findings: list[dict[str, str]]) -> None:
    prefix = f"profile.{name}"
    config = spec["config"]
    config_status = "pass" if config.is_file() and os.access(config, os.R_OK) else "fail"
    add_check(checks, findings, f"{prefix}.config", config_status, str(config) if config_status == "pass" else f"unreadable config: {config}")
    profile_path = spec.get("profile")
    if profile_path:
        profile_status = "pass" if profile_path.is_file() and os.access(profile_path, os.R_OK) else "not_applicable"
        add_check(checks, findings, f"{prefix}.profile", profile_status, str(profile_path) if profile_status == "pass" else "profile.yaml not present")
    for dependency in spec.get("required_files", ()):
        status = "pass" if dependency.exists() and os.access(dependency, os.R_OK) else "fail"
        add_check(checks, findings, f"{prefix}.dependency.{dependency.name}", status, str(dependency))
    service = spec.get("service")
    if spec["lifecycle"] != "active":
        add_check(checks, findings, f"{prefix}.lifecycle", "not_applicable", f"lifecycle={spec['lifecycle']}; standby is not failure")
    elif service:
        active, reason, main_pid = systemd_active(service)
        process_ok = bool(main_pid and pid_alive(main_pid) and (not spec.get("process_marker") or spec["process_marker"] in (process_cmdline(main_pid) or "")))
        if not active:
            add_check(checks, findings, f"{prefix}.service", "fail", f"{service}: {reason}")
        elif not process_ok:
            add_check(checks, findings, f"{prefix}.service_process", "fail", f"{service} active but expected process/PID not verified (pid={main_pid})")
        else:
            add_check(checks, findings, f"{prefix}.service", "pass", f"{service} active pid={main_pid}")
        state_path = spec.get("gateway_state")
        if state_path:
            state, error = read_json(state_path)
        else:
            state, error = None, None
        if state_path and state is None:
            add_check(checks, findings, f"{prefix}.metadata", "warn", f"gateway metadata unavailable: {error or state_path}")
        elif state_path:
            age = metadata_age(state.get("updated_at"))
            stale = age is None or age > STALE_METADATA_SECONDS
            metadata_detail = f"gateway_state={state.get('gateway_state', 'unknown')} age={int(age // 60) if age is not None else 'unknown'}m"
            add_check(
                checks,
                findings,
                f"{prefix}.metadata",
                "warn" if stale else "pass",
                metadata_detail + (" (advisory/stale)" if stale else ""),
                event_type="stale_metadata" if stale else "health_check",
                impact="none" if stale else None,
            )
            platforms = state.get("platforms") if isinstance(state.get("platforms"), dict) else {}
            for channel in spec.get("required_channels", ()):
                channel_data = platforms.get(channel) if isinstance(platforms.get(channel), dict) else {}
                channel_state = channel_data.get("state", "unknown")
                channel_status = "pass" if active and process_ok and channel_state == "connected" else "warn" if active and process_ok else "fail"
                add_check(checks, findings, f"{prefix}.channel.{channel}", channel_status, f"required={channel} metadata_state={channel_state}; live gateway process={'up' if process_ok else 'down'}")
            for channel in spec.get("disabled_channels", ()):
                add_check(checks, findings, f"{prefix}.channel.{channel}", "not_applicable", "disabled/not required for this profile")
        pid_path = spec.get("gateway_pid")
        if pid_path and pid_path.is_file() and main_pid:
            try:
                pid_payload = json.loads(pid_path.read_text(encoding="utf-8"))
                recorded_value = pid_payload.get("pid") if isinstance(pid_payload, dict) else pid_payload
                recorded = int(recorded_value)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                recorded = None
            if recorded != main_pid:
                add_check(checks, findings, f"{prefix}.pid_metadata", "warn", f"gateway.pid={recorded} live_main_pid={main_pid}; advisory metadata mismatch")
            else:
                add_check(checks, findings, f"{prefix}.pid_metadata", "pass", f"gateway.pid matches live pid={main_pid}")
    else:
        add_check(checks, findings, f"{prefix}.service", "not_applicable", "no service required for planned/standby profile")
    for database in spec.get("databases", ()):
        status, detail = check_sqlite(database)
        add_check(checks, findings, f"{prefix}.sqlite.{database.name}", status, f"{database}: {detail}")
    if name == "hermes-coder":
        queue_db = spec["queue_db"]
        if queue_db.is_file():
            try:
                with sqlite3.connect(f"file:{queue_db}?mode=ro", uri=True, timeout=3) as db:
                    rows = db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
                queue_summary = ", ".join(f"{status}={count}" for status, count in rows) or "empty"
                add_check(checks, findings, f"{prefix}.queue", "pass", queue_summary)
            except (sqlite3.Error, OSError) as exc:
                add_check(checks, findings, f"{prefix}.queue", "fail", f"read-only queue probe failed: {exc}")
        else:
            add_check(checks, findings, f"{prefix}.queue", "fail", f"missing queue database: {queue_db}")


def check_scheduler(checks: dict[str, Any], findings: list[dict[str, str]]) -> None:
    status = run_cmd(["hermes", "cron", "status"], timeout=10)
    scheduler_ok = status["ok"] and "Gateway is running" in status["stdout"]
    add_check(checks, findings, "hermes.scheduler", "pass" if scheduler_ok else "fail", status["stdout"].splitlines()[0] if status["stdout"] else status["stderr"] or "scheduler status unavailable")
    if not JOBS_PATH.is_file():
        add_check(checks, findings, "hermes.cron_registry", "fail", f"missing {JOBS_PATH}")
        return
    jobs, error = read_json(JOBS_PATH)
    if jobs is None:
        add_check(checks, findings, "hermes.cron_registry", "fail", error or "invalid jobs JSON")
        return
    raw_jobs = jobs.get("jobs", [])
    if not isinstance(raw_jobs, list):
        add_check(checks, findings, "hermes.cron_registry", "fail", "jobs is not a list")
        return
    active = [job for job in raw_jobs if isinstance(job, dict) and job.get("enabled")]
    overdue: list[str] = []
    failures: list[tuple[str, int, str]] = []
    delivery_failures: list[tuple[str, str]] = []
    for job in active:
        name = str(job.get("name", job.get("id", "unknown")))
        last_status = str(job.get("last_status", ""))
        streak = int(job.get("failure_streak") or 0)
        if streak or last_status in {"error", "failed"}:
            failures.append((name, streak, last_status or "unknown"))
        delivery_error = str(job.get("last_delivery_error") or "").strip()
        if delivery_error:
            delivery_failures.append((name, delivery_error))
        next_run = job.get("next_run_at")
        age = metadata_age(next_run)
        if age is not None and age > 10 * 60:
            overdue.append(name)
    for name, streak, last_status in failures:
        actionable = name in CRITICAL_CRON_JOBS or streak >= NONCRITICAL_CRON_FAILURE_THRESHOLD
        add_check(
            checks,
            findings,
            f"hermes.cron_failure.{name}",
            "warn",
            f"{name} streak={streak} status={last_status}",
            event_type="cron_failure",
            impact="actionable" if actionable else "none",
            fingerprint_key=f"cron:{name}",
        )
    add_check(
        checks,
        findings,
        "hermes.cron_failures",
        "pass",
        "no active job failure streaks" if not failures else f"events={len(failures)}; see per-job findings",
    )
    for name, detail in delivery_failures:
        add_check(
            checks,
            findings,
            f"hermes.cron_delivery.{name}",
            "fail",
            f"{name}: {detail[:300]}",
            event_type="delivery_failure",
            impact="actionable",
            fingerprint_key=f"delivery:{name}",
        )
    add_check(
        checks,
        findings,
        "hermes.cron_delivery",
        "pass",
        "no recorded delivery failures" if not delivery_failures else f"events={len(delivery_failures)}; see per-job findings",
    )
    add_check(checks, findings, "hermes.cron_overdue", "warn" if overdue else "pass", ", ".join(overdue[:6]) if overdue else "no overdue active jobs")
    add_check(checks, findings, "hermes.cron_registry", "pass", f"active_jobs={len(active)}")


def check_journal(checks: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    units = [spec["service"] for spec in PROFILE_REGISTRY.values() if spec.get("service")] + ["hermes-mcp.service", "hermes-proton-worker.service"]
    errors: list[tuple[str, str]] = []
    for unit in units:
        result = run_cmd(["journalctl", "--user", "-u", unit, "--since", RECENT_ERROR_WINDOW, "--no-pager", "-o", "cat"], timeout=8)
        if not result["ok"]:
            continue
        matches = [line.strip() for line in result["stdout"].splitlines() if re.search(r"\b(error|failed|traceback|exception)\b", line, re.IGNORECASE)]
        if matches:
            errors.append((unit, matches[-1][:180]))
    for unit, detail in errors:
        policy_event = "RobotsBlocked" in detail or "robots policy" in detail.lower()
        normalized_detail = re.sub(r"\d{4}-\d{2}-\d{2}[^ ]*", "", detail)
        normalized_detail = re.sub(r"\b\d{2}:\d{2}:\d{2}(?:[,.]\d+)?\b", "", normalized_detail)
        normalized_detail = re.sub(r"\b(pid|attempt|retry)=\d+\b", r"\1=<n>", normalized_detail, flags=re.IGNORECASE)
        normalized_detail = re.sub(r"\s+", " ", normalized_detail).strip()[:160]
        add_check(
            checks,
            findings,
            f"host.recent_relevant_errors.{unit}",
            "warn",
            detail,
            event_type="expected_policy_block" if policy_event else "journal_error",
            impact="none" if policy_event else "actionable",
            fingerprint_key=f"{unit}:robots-blocked" if policy_event else f"{unit}:{normalized_detail}",
        )
    add_check(
        checks,
        findings,
        "host.recent_relevant_errors",
        "pass",
        "none detected in selected user services" if not errors else f"events={len(errors)}; see per-service findings",
    )


def collect(scenario: str) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    check_host(checks, findings)
    check_ollama(checks, findings)
    for name, spec in PROFILE_REGISTRY.items():
        check_profile(name, spec, checks, findings)
    check_scheduler(checks, findings)
    check_journal(checks, findings)
    if scenario == "fail":
        add_check(checks, findings, "test.synthetic_failure", "fail", "synthetic failure scenario")
    elif scenario == "warn":
        add_check(checks, findings, "test.synthetic_warning", "warn", "synthetic warning scenario")
    actionable = [item for item in findings if item.get("impact") != "none"]
    severity = "critical" if any(item["severity"] == "fail" for item in actionable) else "degraded" if actionable else "healthy"
    return {"schema": "hve.spark.health.v2", "collected_at": iso(), "overall": severity, "alert_route": ALERT_ROUTE, "included_profiles": list(PROFILE_REGISTRY), "excluded_profiles": ["hanshermesagentcollector", "default"], "checks": checks, "findings": findings}


def fingerprint(item: dict[str, str]) -> str:
    key = str(item.get("fingerprint_key") or item["id"])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def load_state(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {"schema": "hve.spark.health.alert-state.v1", "incidents": {}}, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"schema": "hve.spark.health.alert-state.v1", "incidents": {}}, f"alert state unreadable: {exc}"
    if not isinstance(value, dict) or not isinstance(value.get("incidents", {}), dict):
        return {"schema": "hve.spark.health.alert-state.v1", "incidents": {}}, "alert state has invalid shape"
    return value, None


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".new")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def transition_alerts(data: dict[str, Any], state_path: Path, evidence_dir: Path) -> tuple[list[str], Path]:
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_path = evidence_dir / f"{now().strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(evidence_path, 0o600)
    lock_path = state_path.with_name(state_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state, state_error = load_state(state_path)
        previous = state.get("incidents", {})
        current: dict[str, dict[str, Any]] = {}
        legacy_messages: list[str] = []
        if state_error:
            legacy_messages.append(f"ALERT state: {state_error}")
        for item in data["findings"]:
            fp = fingerprint(item)
            old = previous.get(fp)
            record = {
                "id": item["id"],
                "severity": item["severity"],
                "event_type": item.get("event_type", "health_check"),
                "impact": item.get("impact", "actionable"),
                "detail": item["detail"],
                "last_seen": iso(),
                "first_seen": old.get("first_seen", iso()) if isinstance(old, dict) else iso(),
                "occurrences": int(old.get("occurrences", 0)) + 1 if isinstance(old, dict) else 1,
            }
            current[fp] = record
            if not isinstance(old, dict):
                label = "ADVISORY" if item.get("impact") == "none" else item["severity"].upper()
                legacy_messages.append(f"NEW {label} {item['id']}: {item['detail']}")
            elif (
                old.get("severity") != item["severity"]
                or old.get("impact") != item.get("impact", "actionable")
            ):
                old_rank = {"warn": 1, "fail": 2}.get(str(old.get("severity")), 0)
                new_rank = {"warn": 1, "fail": 2}.get(item["severity"], 0)
                old_impact_rank = 1 if old.get("impact") != "none" else 0
                new_impact_rank = 1 if item.get("impact") != "none" else 0
                transition = "WORSENING" if (new_rank, new_impact_rank) > (old_rank, old_impact_rank) else "IMPROVED"
                label = "ADVISORY" if item.get("impact") == "none" else item["severity"].upper()
                legacy_messages.append(f"{transition} {label} {item['id']}: {item['detail']}")
        for fp, old in previous.items():
            if fp not in current and isinstance(old, dict):
                label = "ADVISORY" if old.get("impact") == "none" else str(old.get("severity", "warn")).upper()
                legacy_messages.append(f"RECOVERY {label} {old.get('id', fp)}")
        state = {
            "schema": "hve.spark.health.alert-state.v2",
            "updated_at": iso(),
            "incidents": current,
        }
        save_state(state_path, state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    with ReliabilityStore(Path(os.environ.get("HVE_RELIABILITY_DB", str(DEFAULT_RELIABILITY_DB)))) as store:
        triage = store.ingest(data, legacy_messages=legacy_messages)
    mode = os.environ.get("HVE_WATCHDOG_TRIAGE_MODE", "suppress_advisories").strip().lower()
    if mode in {"legacy", "shadow"}:
        return legacy_messages, evidence_path
    state_messages = [message for message in legacy_messages if message.startswith("ALERT state:")]
    return state_messages + triage.messages, evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("normal", "fail", "warn"), default="normal", help="deterministic validation injection; normal is production mode")
    parser.add_argument("--state-path", type=Path, default=Path(os.environ.get("HVE_WATCHDOG_STATE", DEFAULT_STATE)))
    parser.add_argument("--evidence-dir", type=Path, default=Path(os.environ.get("HVE_WATCHDOG_EVIDENCE", DEFAULT_EVIDENCE)))
    parser.add_argument("--db-path", type=Path, default=Path(os.environ.get("HVE_RELIABILITY_DB", DEFAULT_RELIABILITY_DB)))
    args = parser.parse_args()
    data = collect(args.scenario)
    os.environ["HVE_RELIABILITY_DB"] = str(args.db_path)
    try:
        messages, evidence_path = transition_alerts(data, args.state_path, args.evidence_dir)
    except ReliabilityStoreError as exc:
        print(f"HVE reliability store failure: {exc}")
        return 1
    if messages:
        print(f"HVE Spark health alert — {data['overall'].upper()} ({iso()})")
        print(f"Route: {ALERT_ROUTE}")
        for message in messages:
            print(f"• {message}")
        print(f"Evidence: {evidence_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
