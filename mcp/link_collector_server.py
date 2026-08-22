#!/home/hans/.hermes/hermes-agent/venv/bin/python

from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.link_collector import archive_link as collect_link  # noqa: E402
from tools.pdf_collector import archive_pdf as collect_pdf  # noqa: E402


mcp = FastMCP(
    "HVE Telegram Link Collector",
    instructions=(
            "This server exposes restricted tools for archiving public web links and "
            "Telegram PDF attachments into the local HVE knowledge library."
    ),
)


@mcp.tool()
def archive_link(url: str, capture_context: str | None = None) -> dict:
    """Archive one public HTTP(S) URL with optional Telegram capture context."""
    try:
        return collect_link(url, capture_context)
    except Exception as exc:
        return {
            "status": "internal_error",
            "archived": False,
            "fetched": False,
            "extracted": False,
            "indexed": False,
            "duplicate": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool()
def archive_pdf(pdf_path: str, capture_context: str | None = None) -> dict:
    """Archive one Telegram PDF attachment into the durable HVE knowledge library."""
    try:
        return collect_pdf(pdf_path, capture_context)
    except Exception as exc:
        return {
            "status": "internal_error",
            "archived": False,
            "indexed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
