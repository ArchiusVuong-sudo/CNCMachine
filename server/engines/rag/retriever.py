"""pgvector retriever — Supabase RPC wrapper.

Two callables surface the index to the RAG planner:

  * :func:`retrieve_analogues`  — top-K analogue parts from
    ``rag_part_embeddings`` (vector ANN + optional hard filters)
  * :func:`retrieve_patterns`   — top-K pattern chunks from
    ``rag_pattern_chunks`` (optional, OOD safety net)

Both calls go through the Postgres RPCs declared in ``ingestion/schema.sql``
(``rag_search_parts``, ``rag_search_patterns``) — that keeps the SQL
co-located with the schema and lets us evolve the ranking heuristic
without redeploying the server.

Failure mode
------------
If pgvector / Supabase / OpenAI is unavailable, every public function
returns an empty list. The planner treats an empty result as "no
analogues" and lets the LLM synthesize without prior evidence (degrading
to general patterns + catalog only). This mirrors the agentic engine's
own degradation behavior.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...core.settings import get_settings
from ...infra.supabase import get_supabase_client
from .embed import embed_text

logger = logging.getLogger("cncserver.engines.rag.retriever")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def retrieve_analogues(
    *,
    query_text: str,
    part_type: str | None,
    material_family: str | None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Return the top-K nearest analogue parts to ``query_text``.

    Hard filters: ``part_type`` and ``material_family``. If both are
    supplied and the filtered ANN returns nothing, we retry without the
    filters (vector-only) so the LLM at least sees the closest semantic
    matches. The fallback is logged so the planner can flag low-confidence
    output downstream.
    """
    settings = get_settings().rag
    top_k = top_k or settings.rag_top_k

    query_emb = await embed_text(query_text)
    if query_emb is None:
        logger.warning("retrieve_analogues: embed failed — returning [] for query of %d chars", len(query_text))
        return []

    client = get_supabase_client()
    if client is None:
        logger.warning("retrieve_analogues: supabase client unavailable — returning []")
        return []

    rows = await _rpc_search_parts(
        client, query_emb,
        material_family=material_family or None,
        part_type=part_type or None,
        match_count=top_k,
    )

    if not rows and (material_family or part_type):
        logger.info(
            "retrieve_analogues: hard-filtered query returned 0 rows "
            "(part_type=%r material_family=%r); retrying vector-only",
            part_type, material_family,
        )
        rows = await _rpc_search_parts(
            client, query_emb,
            material_family=None, part_type=None,
            match_count=top_k,
        )
        for row in rows:
            row["_filter_fallback"] = True

    logger.info(
        "retrieve_analogues: returned %d row(s) (top_k=%d, filters: pt=%r, fam=%r)",
        len(rows), top_k, part_type, material_family,
    )
    return rows


async def retrieve_patterns(
    *,
    query_text: str,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Return top-K pattern chunks from ``rag_pattern_chunks``.

    The planner only calls this when analogue retrieval is weak (no
    family match, similarity below threshold) so the LLM still has some
    grounded reasoning material.
    """
    settings = get_settings().rag
    top_k = top_k or settings.rag_top_k_patterns

    query_emb = await embed_text(query_text)
    if query_emb is None:
        return []

    client = get_supabase_client()
    if client is None:
        return []

    return await _rpc_search_patterns(client, query_emb, match_count=top_k)


# ---------------------------------------------------------------------------
# Supabase RPC plumbing
# ---------------------------------------------------------------------------

def _to_thread(callable_, *args, **kwargs):
    """Run a blocking call on the default executor and return a coroutine."""
    return asyncio.get_running_loop().run_in_executor(None, lambda: callable_(*args, **kwargs))


async def _rpc_search_parts(
    client: Any,
    query_embedding: list[float],
    *,
    material_family: str | None,
    part_type: str | None,
    match_count: int,
) -> list[dict[str, Any]]:
    """Call ``rag_search_parts`` RPC. Returns [] on any error."""
    payload = {
        "query_embedding":         query_embedding,
        "filter_material_family":  material_family,
        "filter_part_type":        part_type,
        "match_count":             int(match_count),
    }
    try:
        result = await _to_thread(
            lambda: client.rpc("rag_search_parts", payload).execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_search_parts RPC failed: %s", exc)
        return []

    data = getattr(result, "data", None) or []
    if not isinstance(data, list):
        logger.warning("rag_search_parts RPC: unexpected response shape: %r", type(data))
        return []
    return data


async def _rpc_search_patterns(
    client: Any,
    query_embedding: list[float],
    *,
    match_count: int,
) -> list[dict[str, Any]]:
    """Call ``rag_search_patterns`` RPC. Returns [] on any error."""
    payload = {
        "query_embedding": query_embedding,
        "match_count":     int(match_count),
    }
    try:
        result = await _to_thread(
            lambda: client.rpc("rag_search_patterns", payload).execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_search_patterns RPC failed: %s", exc)
        return []

    data = getattr(result, "data", None) or []
    if not isinstance(data, list):
        return []
    return data


__all__ = ["retrieve_analogues", "retrieve_patterns"]
