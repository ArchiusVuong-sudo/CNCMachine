"""OpenAI embeddings client for the RAG engine.

A thin async wrapper around ``POST {OPENAI_BASE_URL}/embeddings`` so the
ingestion CLI and the query-time retriever share one code path.

Why httpx and not the ``openai`` SDK
------------------------------------
The rest of the server already speaks httpx (see :mod:`server.infra.llm`).
Keeping embeddings on the same client avoids dragging the openai SDK and
its transitive deps into a server that's otherwise dependency-light. The
embeddings endpoint is one URL, two fields, and a JSON response — not
worth a SDK.

Configuration
-------------
Reads from :class:`server.core.settings.RagSettings`:

  * ``openai_api_key``        — required; returns ``None`` per call if missing
  * ``openai_base_url``       — default ``https://api.openai.com/v1``
  * ``openai_embedding_model`` — default ``text-embedding-3-small`` (1536-dim)

Behavior on misconfiguration
----------------------------
If ``OPENAI_API_KEY`` is missing or the request fails, :func:`embed_text`
returns ``None`` (logging a warning). Callers MUST handle the ``None``
case — typically by skipping retrieval for that component and letting
the LLM synthesize without analogues, OR by marking the component
failed.
"""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from ...core.settings import get_settings

logger = logging.getLogger("cncserver.engines.rag.embed")

# A single AsyncClient reused across calls inside one ingestion / query.
_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _resolve_credentials() -> tuple[str | None, str, str]:
    """Pull (api_key, base_url, model) from settings. ``api_key`` may be ``None``."""
    cfg = get_settings().rag
    return cfg.openai_api_key, cfg.openai_base_url.rstrip("/"), cfg.openai_embedding_model


async def embed_text(text: str) -> list[float] | None:
    """Embed one string. Returns the float vector, or ``None`` on failure.

    The embedding endpoint also accepts batched input; we expose a
    convenience batched variant below for the ingestion CLI.
    """
    if not text or not text.strip():
        logger.warning("embed_text: empty input — skipping")
        return None
    vectors = await embed_batch([text])
    if not vectors:
        return None
    return vectors[0]


async def embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Embed a list of strings in one call. Returns ``None`` on failure.

    OpenAI's embedding endpoint accepts a list of up to ~2048 inputs per
    request; we don't enforce a cap here because our largest batch (the
    52-part ingest) is well under that.
    """
    api_key, base_url, model = _resolve_credentials()
    if not api_key:
        logger.warning(
            "embed_batch: OPENAI_API_KEY missing — RAG retrieval will be disabled. "
            "Set OPENAI_API_KEY in server/.env to enable embeddings."
        )
        return None

    cleaned = [t for t in texts if (t or "").strip()]
    if not cleaned:
        return None

    payload = {"model": model, "input": cleaned, "encoding_format": "float"}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{base_url}/embeddings"

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("embed_batch: HTTP error (%s)", exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "embed_batch: HTTP %d — %s",
            resp.status_code, resp.text[:200],
        )
        return None

    body = resp.json()
    data = body.get("data") or []
    if len(data) != len(cleaned):
        logger.warning(
            "embed_batch: expected %d vectors, got %d", len(cleaned), len(data),
        )
    out: list[list[float]] = []
    for item in data:
        vec = item.get("embedding")
        if isinstance(vec, list):
            out.append([float(x) for x in vec])
    return out or None


__all__ = ["embed_text", "embed_batch"]
