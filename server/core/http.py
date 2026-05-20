"""Tiny HTTP helpers used by the pipeline.

We deliberately keep this thin — engines that talk to external services
(LLM endpoint, Supabase) own their own httpx clients with appropriate
timeouts. This module is for one-shot file downloads only.
"""
from __future__ import annotations

import httpx


async def download_bytes(url: str, *, timeout_seconds: float = 60.0) -> bytes:
    """GET a URL and return the response body. Raises on non-2xx."""
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
