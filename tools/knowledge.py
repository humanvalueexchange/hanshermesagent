from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from tools.knowledge_layer_client import (
    KNOWLEDGE_INSTALL_ROOT,
    KNOWLEDGE_PYTHON,
    KNOWLEDGE_ROOT,
    cli_command,
)

RunCommand = Callable[[list[str], int], tuple[int, str]]

HVE_LIBRARY_ROOT = KNOWLEDGE_ROOT
PROCESSED_TEXT_DIR = HVE_LIBRARY_ROOT / "processed" / "text"
KNOWLEDGE_VENV_PYTHON = KNOWLEDGE_PYTHON
KNOWLEDGE_SEARCH_SCRIPT = KNOWLEDGE_INSTALL_ROOT / "src" / "hve_knowledge_layer" / "cli.py"
MAX_RESULTS = 20
SEMANTIC_SEARCH_TIMEOUT = 120


def _clamp_max_results(max_results: int) -> int:
    try:
        value = int(max_results)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, MAX_RESULTS))


def _format_pages(value: object) -> str:
    if value is None:
        return "unknown"
    pages = str(value).strip()
    return pages or "unknown"


def _format_score(value: object) -> str | None:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return None


def _format_excerpt(value: object) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "(no excerpt available)"
    if len(text) <= 320:
        return text
    return f"{text[:317].rstrip()}..."


def _format_semantic_results(query: str, rows: list[dict]) -> str:
    if not rows:
        return f"No results found for '{query}' in HVE library."

    results = []
    for row in rows:
        page_start = row.get("page_start")
        page_end = row.get("page_end")
        pages = row.get("pages")
        if pages is None:
            if page_start is None and page_end is None:
                pages = None
            elif page_start == page_end:
                pages = str(page_start)
            else:
                pages = f"{page_start or '?'}-{page_end or '?'}"
        excerpt = row.get("excerpt") or row.get("text")
        parts = [
            f"### {row.get('book') or 'Unknown source'}",
            f"Author: {row.get('author') or 'Unknown'}",
            f"Chapter: {row.get('chapter') or 'Unknown'}",
            f"Pages: {_format_pages(pages)}",
        ]
        score = row.get("score")
        if score is None and row.get("_distance") is not None:
            score = max(0.0, 1 - float(row["_distance"]))
        score = _format_score(score)
        if score is not None:
            parts.append(f"Score: {score}")
        parts.append(f"Excerpt: {_format_excerpt(excerpt)}")
        results.append("\n".join(parts))

    header = f"Found {len(rows)} semantic result(s) for '{query}' in HVE library:\n\n"
    return header + "\n\n---\n\n".join(results)


def _fallback_grep_search(
    query: str, max_results: int, run_command: RunCommand
) -> list[dict[str, str]]:
    if not PROCESSED_TEXT_DIR.exists():
        return []

    code, output = run_command(
        ["grep", "-r", "-i", "-l", "--include=*.txt", query, str(PROCESSED_TEXT_DIR)],
        15,
    )
    if code != 0 or not output.strip():
        return []

    matched_files = output.strip().splitlines()[:max_results]
    results: list[dict[str, str]] = []
    for fpath in matched_files:
        file_path = Path(fpath)
        relative = file_path.relative_to(PROCESSED_TEXT_DIR)
        _, lines = run_command(["grep", "-i", "-n", "-m", "10", query, fpath], 10)
        snippet = _format_excerpt(lines)
        results.append(
            {
                "path": str(relative),
                "excerpt": snippet,
            }
        )
    return results


def _format_fallback_results(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"No results found for '{query}' in HVE library."
    formatted = [
        f"### {result['path']}\nExcerpt: {result['excerpt']}" for result in results
    ]
    header = (
        f"Semantic search unavailable. Found {len(results)} fallback result(s) "
        f"for '{query}':\n\n"
    )
    return header + "\n\n---\n\n".join(formatted)


def search_knowledge_vault_machine(
    query: str, max_results: int, run_command: RunCommand
) -> dict:
    """Return retrieval mode, backend health, and bounded result data."""
    safe_max_results = _clamp_max_results(max_results)
    backend_error = None
    if KNOWLEDGE_VENV_PYTHON.exists() and KNOWLEDGE_SEARCH_SCRIPT.exists():
        code, output = run_command(
            cli_command("query", query, "--top-k", str(safe_max_results)),
            SEMANTIC_SEARCH_TIMEOUT,
        )
        if code == 0:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                backend_error = f"invalid semantic response: {exc}"
            else:
                if isinstance(payload, list):
                    return {
                        "retrieval_mode": "semantic",
                        "semantic_available": True,
                        "fallback_used": False,
                        "backend_error": None,
                        "results": payload,
                    }
                backend_error = "semantic response was not a result list"
        else:
            backend_error = output or f"semantic query exited with status {code}"
    else:
        backend_error = "semantic query runtime is unavailable"

    return {
        "retrieval_mode": "keyword_fallback",
        "semantic_available": False,
        "fallback_used": True,
        "backend_error": backend_error,
        "results": _fallback_grep_search(query, safe_max_results, run_command),
    }


def search_knowledge_vault(query: str, max_results: int, run_command: RunCommand) -> str:
    result = search_knowledge_vault_machine(query, max_results, run_command)
    if result["retrieval_mode"] == "semantic":
        return _format_semantic_results(query, result["results"])
    return _format_fallback_results(query, result["results"])
