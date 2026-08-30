"""Lightpanda-backed web extraction for local Hermes research."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 45
_MAX_TIMEOUT_SECONDS = 120
_MAX_CONTENT_CHARS = 9000
_NAVIGATION_LINES = {
    "menu",
    "search",
    "skip to main content",
    "skip to footer",
    "x",
}


def _binary_path() -> str:
    configured = os.getenv("LIGHTPANDA_BINARY", "").strip()
    if configured:
        return configured
    return shutil.which("lightpanda") or str(Path.home() / ".local" / "bin" / "lightpanda")


def _safe_timeout(value: Any) -> int:
    try:
        return max(5, min(int(value), _MAX_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS


def _safe_max_chars(value: Any) -> int:
    try:
        return max(1, min(int(value), _MAX_CONTENT_CHARS))
    except (TypeError, ValueError):
        return _MAX_CONTENT_CHARS


def _title_from_markdown(content: str, url: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return urlparse(url).netloc


def _clean_markdown(content: str) -> str:
    """Remove common page chrome while preserving article markdown."""
    cleaned: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower() in _NAVIGATION_LINES:
            continue
        if re.fullmatch(r"\[!\[[^\]]*\]\([^)]+\)\]\([^)]+\)", stripped):
            continue
        cleaned.append(line.rstrip())
    return "\n".join(cleaned).strip()


class LightpandaWebSearchProvider(WebSearchProvider):
    """Extract rendered page content using the local Lightpanda binary."""

    @property
    def name(self) -> str:
        return "lightpanda"

    @property
    def display_name(self) -> str:
        return "Lightpanda (Local)"

    def is_available(self) -> bool:
        path = Path(_binary_path())
        return path.is_file() and os.access(path, os.X_OK)

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        max_chars = _safe_max_chars(kwargs.get("max_chars", _MAX_CONTENT_CHARS))
        timeout = _safe_timeout(kwargs.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
        binary = _binary_path()
        results: list[dict[str, Any]] = []

        for raw_url in urls:
            url = str(raw_url).strip()
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                results.append({"url": url, "title": "", "content": "", "raw_content": "", "metadata": {}, "error": "Only absolute HTTP(S) URLs are supported"})
                continue

            try:
                from tools.environments.local import _sanitize_subprocess_env

                env = _sanitize_subprocess_env(dict(os.environ))
                env["LIGHTPANDA_DISABLE_TELEMETRY"] = "true"
                completed = subprocess.run(
                    [
                        binary,
                        "fetch",
                        "--obey-robots",
                        "--dump",
                        "markdown",
                        "--log-level",
                        "error",
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=env,
                )
            except FileNotFoundError:
                return [{"url": url, "title": "", "content": "", "raw_content": "", "metadata": {}, "error": f"Lightpanda binary not found: {binary}"} for url in urls]
            except subprocess.TimeoutExpired:
                results.append({"url": url, "title": "", "content": "", "raw_content": "", "metadata": {}, "error": f"Lightpanda timed out after {timeout}s"})
                continue

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip().replace("\n", " ")
                results.append({"url": url, "title": "", "content": "", "raw_content": "", "metadata": {}, "error": f"Lightpanda exited with code {completed.returncode}: {detail[:500]}"})
                continue

            content = _clean_markdown(completed.stdout)
            if not content:
                results.append({"url": url, "title": "", "content": "", "raw_content": "", "metadata": {}, "error": "Lightpanda returned empty content"})
                continue

            truncated = len(content) > max_chars
            content = content[:max_chars]
            results.append(
                {
                    "url": url,
                    "title": _title_from_markdown(content, url),
                    "content": content,
                    "raw_content": content,
                    "metadata": {
                        "provider": self.name,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "truncated": truncated,
                    },
                }
            )

        logger.info("Lightpanda extracted %d/%d URL(s)", sum("error" not in item for item in results), len(urls))
        return results

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Lightpanda (Local)",
            "badge": "local · ARM64",
            "tag": "Local JavaScript-capable extraction using the Lightpanda browser.",
            "env_vars": [
                {
                    "key": "LIGHTPANDA_BINARY",
                    "prompt": "Optional Lightpanda binary path",
                    "url": "https://github.com/lightpanda-io/browser/releases",
                }
            ],
        }
