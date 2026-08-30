#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

REPO_DIR = Path.home() / "hanshermesagent"
BRIEFINGS_DIR = REPO_DIR / "logs" / "briefings"
HERMES_ROOT = Path.home() / ".hermes"
MAIN_PROFILE = HERMES_ROOT / "profiles" / "main"
CRON_JOBS_PATH = MAIN_PROFILE / "cron" / "jobs.json"
BTC_DATA_PATH = Path.home() / "freqtrade" / "user_data" / "data" / "BTC_USD-1m.feather"
SERVICE_NAMES = (
    "ollama",
    "open-webui",
)
USER_SERVICE_NAMES = (
    "hermes-gateway",
    "hermes-telegram-log",
    "hermes-freqtrade",
)

@dataclass
class Forecast:
    current_price: float
    predicted_price: float
    direction: str
    confidence: str
    rationale: str
    invalidation: str
    source: str


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_briefings_dir() -> None:
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str], timeout: int = 20, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def system_service_state(name: str) -> str:
    code, stdout, _ = run_command(["systemctl", "is-active", name], timeout=10)
    return stdout if code == 0 and stdout else "inactive"


def user_service_state(name: str) -> str:
    code, stdout, _ = run_command(["systemctl", "--user", "is-active", name], timeout=10)
    return stdout if code == 0 and stdout else "inactive"


def file_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    stat = path.stat()
    return f"present ({stat.st_size} bytes, mtime {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='minutes')})"


def git_head(repo_dir: Path) -> str:
    code, stdout, stderr = run_command(["git", "-C", str(repo_dir), "rev-parse", "--short", "HEAD"], timeout=10)
    if code != 0:
        return f"unknown ({stderr or 'git rev-parse failed'})"
    return stdout


def git_branch(repo_dir: Path) -> str:
    code, stdout, stderr = run_command(["git", "-C", str(repo_dir), "branch", "--show-current"], timeout=10)
    if code != 0:
        return f"unknown ({stderr or 'git branch failed'})"
    return stdout or "detached"


def load_cron_jobs() -> list[dict]:
    if not CRON_JOBS_PATH.exists():
        return []
    data = json.loads(CRON_JOBS_PATH.read_text(encoding="utf-8"))
    return data.get("jobs", [])


def get_last_cron_output(job_name: str) -> str | None:
    """Return the text of the most recent cron output file for the named job, or None."""
    jobs = load_cron_jobs()
    job_id = next((j["id"] for j in jobs if j.get("name") == job_name), None)
    if not job_id:
        return None
    output_dir = MAIN_PROFILE / "cron" / "output" / job_id
    if not output_dir.is_dir():
        return None
    files = sorted(output_dir.glob("*.md"), reverse=True)
    if not files:
        return None
    return files[0].read_text(encoding="utf-8")


def markdown_list(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def fetch_json(url: str, timeout: int = 15) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": "HermesCron/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def fetch_json_with_retry(url: str, attempts: int = 2, timeout: int = 8) -> dict | list:
    last_exc: Exception = RuntimeError("no attempts made")
    for _ in range(attempts):
        try:
            return fetch_json(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
    raise RuntimeError(f"market data fetch failed after {attempts} attempts: {last_exc}") from last_exc


def build_btc_forecast() -> Forecast:
    ohlc_url = "https://api.kraken.com/0/public/OHLC?pair=XXBTZUSD&interval=1"
    ticker_url = "https://api.kraken.com/0/public/Ticker?pair=XXBTZUSD"
    source = "Kraken public API"
    try:
        ohlc_data = fetch_json_with_retry(ohlc_url)
    except RuntimeError as exc:
        raise RuntimeError(f"market data fetch failed: {exc}") from exc

    if ohlc_data.get("error"):
        raise RuntimeError(f"Kraken OHLC error: {ohlc_data['error']}")

    candles = ohlc_data["result"]["XXBTZUSD"]
    closes = [float(c[4]) for c in candles]
    if len(closes) < 31:
        raise RuntimeError("market data fetch failed: insufficient kline history")

    # Try Ticker for real-time price; fall back to latest OHLC close if unavailable
    current_price = closes[-1]
    try:
        ticker_data = fetch_json_with_retry(ticker_url)
        if not ticker_data.get("error"):
            current_price = float(ticker_data["result"]["XXBTZUSD"]["c"][0])
    except (RuntimeError, KeyError):
        pass  # use OHLC close — typically <60s stale, acceptable for forecast
    return_5 = (closes[-1] - closes[-6]) / closes[-6]
    return_15 = (closes[-1] - closes[-16]) / closes[-16]
    return_30 = (closes[-1] - closes[-31]) / closes[-31]
    momentum = (0.5 * return_5) + (0.3 * return_15) + (0.2 * return_30)
    capped_move = max(min(momentum * 0.6, 0.004), -0.004)
    predicted_price = current_price * (1 + capped_move)

    if capped_move > 0.0005:
        direction = "up"
    elif capped_move < -0.0005:
        direction = "down"
    else:
        direction = "flat"

    agreement = sum(
        1
        for value in (return_5, return_15, return_30)
        if (value > 0 and capped_move > 0) or (value < 0 and capped_move < 0) or (abs(value) < 0.0005 and direction == "flat")
    )
    confidence = "high" if agreement == 3 and abs(capped_move) > 0.001 else "medium" if agreement >= 2 else "low"
    rationale = (
        f"Recent 1m momentum over the last 5, 15, and 30 minutes is "
        f"{return_5:+.2%}, {return_15:+.2%}, and {return_30:+.2%}; "
        f"forecast stays {direction} with {confidence} confidence."
    )
    invalidation = (
        "invalidate if the next 5-minute move breaks the current 15-minute direction "
        "or if Kraken public price data stops updating."
    )
    return Forecast(
        current_price=current_price,
        predicted_price=predicted_price,
        direction=direction,
        confidence=confidence,
        rationale=rationale,
        invalidation=invalidation,
        source=source,
    )
