"""Local Lightpanda web extraction provider."""

from __future__ import annotations

from .provider import LightpandaWebSearchProvider


def register(ctx) -> None:
    """Register the local Lightpanda extraction provider."""
    ctx.register_web_search_provider(LightpandaWebSearchProvider())
