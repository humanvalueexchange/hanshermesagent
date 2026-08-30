from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

RunCommand = Callable[[list[str], int], tuple[int, str]]

HVE_LIBRARY_ROOT = Path("/hve-library")
PROCESSED_TEXT_DIR = HVE_LIBRARY_ROOT / "processed" / "text"
KNOWLEDGE_VENV_PYTHON = Path.home() / ".hve-knowledge" / "venv" / "bin" / "python3"
KNOWLEDGE_SEARCH_SCRIPT = Path.home() / "hanshermesagent" / "mcp" / "tools" / "knowledge" / "search.py"
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
        parts = [
            f"### {row.get('book') or 'Unknown source'}",
            f"Author: {row.get('author') or 'Unknown'}",
            f"Chapter: {row.get('chapter') or 'Unknown'}",
            f"Pages: {_format_pages(row.get('pages'))}",
        ]
        score = _format_score(row.get("score"))
        if score is not None:
            parts.append(f"Score: {score}")
        parts.append(f"Excerpt: {_format_excerpt(row.get('excerpt'))}")
        results.append("\n".join(parts))

    header = f"Found {len(rows)} semantic result(s) for '{query}' in HVE library:\n\n"
    return header + "\n\n---\n\n".join(results)


def _fallback_grep_search(query: str, max_results: int, run_command: RunCommand) -> str:
    if not PROCESSED_TEXT_DIR.exists():
        return "Knowledge library text not found at /hve-library/processed/text."

    code, output = run_command(
        ["grep", "-r", "-i", "-l", "--include=*.txt", query, str(PROCESSED_TEXT_DIR)],
        15,
    )
    if code != 0 or not output.strip():
        return f"No results found for '{query}' in HVE library."

    matched_files = output.strip().splitlines()[:max_results]
    results = []
    for fpath in matched_files:
        file_path = Path(fpath)
        relative = file_path.relative_to(PROCESSED_TEXT_DIR)
        _, lines = run_command(["grep", "-i", "-n", "-m", "10", query, fpath], 10)
        snippet = _format_excerpt(lines)
        results.append(f"### {relative}\nExcerpt: {snippet}")

    header = f"Semantic search unavailable. Found {len(matched_files)} fallback result(s) for '{query}':\n\n"
    return header + "\n\n---\n\n".join(results)


def search_knowledge_vault(query: str, max_results: int, run_command: RunCommand) -> str:
    safe_max_results = _clamp_max_results(max_results)

    if KNOWLEDGE_VENV_PYTHON.exists() and KNOWLEDGE_SEARCH_SCRIPT.exists():
        code, output = run_command(
            [
                str(KNOWLEDGE_VENV_PYTHON),
                str(KNOWLEDGE_SEARCH_SCRIPT),
                "--query",
                query,
                "--max-results",
                str(safe_max_results),
            ],
            SEMANTIC_SEARCH_TIMEOUT,
        )
        if code == 0:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(payload, list):
                    return _format_semantic_results(query, payload)

    return _fallback_grep_search(query, safe_max_results, run_command)
