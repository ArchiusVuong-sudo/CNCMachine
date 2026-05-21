"""CLI: rebuild the RAG index from KNOWLEDGE_BASE/.

Usage::

    # From the repo root with .env populated:
    python -m server.engines.rag.ingestion.build_index --rebuild-all

    # Embed parts only (skip patterns):
    python -m server.engines.rag.ingestion.build_index --parts-only

    # Dry run — no Supabase writes, just shows what would happen:
    python -m server.engines.rag.ingestion.build_index --dry-run

Idempotent — re-running upserts. Safe to wire to a post-edit hook later.

Prerequisites
-------------
1. ``schema.sql`` applied in the target Supabase project (creates the
   pgvector extension, tables, and rpc functions).
2. ``OPENAI_API_KEY`` and ``NEXT_PUBLIC_SUPABASE_URL`` /
   ``SUPABASE_SERVICE_ROLE_KEY`` set in ``server/.env``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Bootstrap so the script can be invoked as ``python -m server.engines.rag...``
# AND directly via path (handy on the pod).
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# .env loader — best-effort so the CLI works without explicit env exports.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / "server" / ".env")
    load_dotenv(_REPO_ROOT / "server" / ".env.local")
except ImportError:
    pass

from server.core.settings import get_settings  # noqa: E402
from server.engines.rag.embed import embed_batch  # noqa: E402
from server.engines.rag.ingestion.descriptors import build_descriptor  # noqa: E402
from server.engines.rag.ingestion.parts_loader import (  # noqa: E402
    PartRecord,
    PatternChunk,
    load_all_parts,
    load_pattern_chunks,
)
from server.infra.supabase import get_supabase_client  # noqa: E402

logger = logging.getLogger("cncserver.engines.rag.ingestion.build_index")


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def _part_row_payload(record: PartRecord, embedding: list[float]) -> dict[str, Any]:
    """Map a PartRecord into a row that matches rag_part_embeddings."""
    return {
        "part_number":      record.part_number,
        "rev":              record.rev or None,
        "material":         record.material or None,
        "material_family":  record.material_family or None,
        "part_type":        record.part_type or None,
        "complexity_class": record.complexity_class or None,
        "envelope_mm":      record.envelope_mm or None,
        "bbox_volume_mm3":  record.bbox_volume_mm3,
        "stock_form":       record.stock_form or None,
        "n_features":       record.n_features,
        "n_ops":            record.n_ops,
        "n_tools":          record.n_tools,
        "total_run_min_pc": record.total_run_min_pc,
        "total_setup_hr":   record.total_setup_hr,
        "cost_ea_act":      record.cost_ea_act,
        "unit_price":       record.unit_price,
        "currency":         record.currency,
        "description":      record.descriptor if hasattr(record, "descriptor") else "",
        "description_embedding": embedding,
        "operations_json":  record.operations,
        "jobcost_json":     record.jobcost,
        "metadata":         {"parts_row": record.parts_row},
        "source_md_path":   record.md_path,
    }


def _pattern_chunk_payload(chunk: PatternChunk, embedding: list[float]) -> dict[str, Any]:
    return {
        "kb_path":         chunk.kb_path,
        "section_heading": chunk.section_heading,
        "chunk_order":     chunk.chunk_order,
        "content":         chunk.content,
        "content_embedding": embedding,
    }


# ---------------------------------------------------------------------------
# Ingestion stages
# ---------------------------------------------------------------------------

async def ingest_parts(client: Any, *, dry_run: bool) -> int:
    records = load_all_parts()
    if not records:
        logger.warning("No part records found — nothing to ingest")
        return 0

    descriptors: list[str] = []
    for r in records:
        d = build_descriptor(r)
        r.descriptor = d  # stash for upsert
        descriptors.append(d)

    logger.info(
        "ingest_parts: embedding %d descriptors (avg %d chars)",
        len(descriptors),
        sum(len(d) for d in descriptors) // max(1, len(descriptors)),
    )

    if dry_run:
        for r in records[:3]:
            print("─" * 78)
            print(f"part_number = {r.part_number}")
            print(r.descriptor)
        print("─" * 78)
        print(f"… {len(records)} parts total. Dry run: no embeddings, no DB writes.")
        return len(records)

    vectors = await embed_batch(descriptors)
    if not vectors or len(vectors) != len(descriptors):
        logger.error(
            "embedding failed (got %d/%d vectors) — aborting ingest_parts",
            len(vectors or []), len(descriptors),
        )
        return 0

    rows = [_part_row_payload(r, v) for r, v in zip(records, vectors)]
    return _upsert(client, "rag_part_embeddings", rows, on_conflict="part_number")


async def ingest_patterns(client: Any, *, dry_run: bool) -> int:
    chunks = load_pattern_chunks()
    if not chunks:
        logger.info("No pattern chunks found — skipping")
        return 0

    contents = [c.content for c in chunks]
    logger.info("ingest_patterns: embedding %d chunks", len(contents))

    if dry_run:
        for c in chunks[:3]:
            print("─" * 78)
            print(f"{c.kb_path} :: {c.section_heading} (#{c.chunk_order})")
            print(c.content[:400])
        print("─" * 78)
        print(f"… {len(chunks)} chunks total. Dry run.")
        return len(chunks)

    vectors = await embed_batch(contents)
    if not vectors or len(vectors) != len(contents):
        logger.error(
            "embedding failed (got %d/%d vectors) — aborting ingest_patterns",
            len(vectors or []), len(contents),
        )
        return 0

    rows = [_pattern_chunk_payload(c, v) for c, v in zip(chunks, vectors)]
    return _upsert(client, "rag_pattern_chunks", rows, on_conflict="kb_path,chunk_order")


def _upsert(client: Any, table: str, rows: list[dict], *, on_conflict: str) -> int:
    """Upsert in batches; returns the row count that was sent."""
    if client is None:
        logger.error("supabase client unavailable — set NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")
        return 0
    batch_size = 50
    sent = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            client.table(table).upsert(batch, on_conflict=on_conflict).execute()
            sent += len(batch)
        except Exception as exc:  # noqa: BLE001
            logger.exception("upsert into %s batch %d-%d failed: %s",
                             table, i, i + len(batch), exc)
            return sent
    logger.info("upsert %s: %d row(s) sent", table, sent)
    return sent


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main_async(args: argparse.Namespace) -> int:
    settings = get_settings().rag
    if not settings.openai_api_key and not args.dry_run:
        print("OPENAI_API_KEY missing — set it in server/.env or pass --dry-run", file=sys.stderr)
        return 2

    client = None if args.dry_run else get_supabase_client()
    if client is None and not args.dry_run:
        print(
            "Supabase client unavailable. Set NEXT_PUBLIC_SUPABASE_URL "
            "and SUPABASE_SERVICE_ROLE_KEY in server/.env, then re-run.",
            file=sys.stderr,
        )
        return 3

    parts_count = 0
    patterns_count = 0

    if not args.patterns_only:
        parts_count = await ingest_parts(client, dry_run=args.dry_run)

    if not args.parts_only:
        patterns_count = await ingest_patterns(client, dry_run=args.dry_run)

    print(f"DONE — parts: {parts_count}  patterns: {patterns_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the pgvector index for the RAG engine.",
    )
    parser.add_argument("--rebuild-all", action="store_true",
                        help="Ingest both parts and patterns (default).")
    parser.add_argument("--parts-only", action="store_true",
                        help="Ingest only parts.csv-derived records.")
    parser.add_argument("--patterns-only", action="store_true",
                        help="Ingest only patterns/*.md chunks.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print descriptors but skip embeddings + DB writes.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
