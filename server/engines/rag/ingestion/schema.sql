-- ============================================================================
-- pgvector schema for the RAG engine
--
-- Apply once per Supabase project (or re-apply; everything is idempotent).
-- Run via the Supabase SQL editor, or `psql $DATABASE_URL -f schema.sql`.
--
-- Tables
--   rag_part_embeddings   — one row per analogue part (KB-derived)
--   rag_pattern_chunks    — one row per H2 chunk of KNOWLEDGE_BASE/patterns/
--   engine_evaluations    — A/B comparison log between RAG and agentic
--
-- RPCs (called from supabase-py via .rpc())
--   rag_search_parts      — vector ANN + optional hard filters
--   rag_search_patterns   — vector ANN over pattern chunks
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ----------------------------------------------------------------------------
-- rag_part_embeddings
-- ----------------------------------------------------------------------------
-- Embedding dim = 1536 = text-embedding-3-small.
-- If you switch model, drop and recreate (pgvector won't auto-resize).

CREATE TABLE IF NOT EXISTS rag_part_embeddings (
    part_number          TEXT PRIMARY KEY,
    rev                  TEXT,
    material             TEXT,
    material_family      TEXT,
    part_type            TEXT,
    complexity_class     TEXT,
    envelope_mm          TEXT,
    bbox_volume_mm3      NUMERIC,
    stock_form           TEXT,
    n_features           INTEGER,
    n_ops                INTEGER,
    n_tools              INTEGER,
    total_run_min_pc     NUMERIC,
    total_setup_hr       NUMERIC,
    cost_ea_act          NUMERIC,
    unit_price           NUMERIC,
    currency             TEXT,
    description          TEXT NOT NULL,
    description_embedding VECTOR(1536),
    operations_json      JSONB,
    jobcost_json         JSONB,
    metadata             JSONB,
    source_md_path       TEXT,
    ingested_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rag_parts_embedding_hnsw
    ON rag_part_embeddings
    USING hnsw (description_embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS rag_parts_material_family_idx
    ON rag_part_embeddings (material_family);

CREATE INDEX IF NOT EXISTS rag_parts_part_type_idx
    ON rag_part_embeddings (part_type);


-- ----------------------------------------------------------------------------
-- rag_pattern_chunks
-- ----------------------------------------------------------------------------
-- Optional second-tier index over KNOWLEDGE_BASE/patterns/*.md, chunked by H2.

CREATE TABLE IF NOT EXISTS rag_pattern_chunks (
    id                BIGSERIAL PRIMARY KEY,
    kb_path           TEXT NOT NULL,
    section_heading   TEXT,
    chunk_order       INTEGER NOT NULL,
    content           TEXT NOT NULL,
    content_embedding VECTOR(1536),
    metadata          JSONB,
    ingested_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (kb_path, chunk_order)
);

CREATE INDEX IF NOT EXISTS rag_pattern_chunks_hnsw
    ON rag_pattern_chunks
    USING hnsw (content_embedding vector_cosine_ops);


-- ----------------------------------------------------------------------------
-- engine_evaluations
-- ----------------------------------------------------------------------------
-- One row per (analysis_id, engine, component) — drives the A/B study.

CREATE TABLE IF NOT EXISTS engine_evaluations (
    id                       BIGSERIAL PRIMARY KEY,
    analysis_id              TEXT NOT NULL,
    engine                   TEXT NOT NULL,      -- 'agentic' | 'rag'
    file_name                TEXT,
    component_index          INTEGER,
    component_name           TEXT,
    part_number              TEXT,
    material                 TEXT,
    predicted_total_usd      NUMERIC,
    predicted_total_min      NUMERIC,
    predicted_setup_min      NUMERIC,
    predicted_op_codes       JSONB,
    retrieved_analogues      JSONB,
    latency_ms               INTEGER,
    llm_tokens_in            INTEGER,
    llm_tokens_out           INTEGER,
    notes                    TEXT,
    created_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS engine_evaluations_analysis_idx
    ON engine_evaluations (analysis_id);
CREATE INDEX IF NOT EXISTS engine_evaluations_engine_idx
    ON engine_evaluations (engine);
CREATE INDEX IF NOT EXISTS engine_evaluations_part_idx
    ON engine_evaluations (part_number);


-- ----------------------------------------------------------------------------
-- RPC: rag_search_parts
-- ----------------------------------------------------------------------------
-- Cosine similarity ANN over rag_part_embeddings, with optional hard filters.
-- Returns top_k rows ordered by similarity (highest first).
--
-- Call from supabase-py:
--   client.rpc("rag_search_parts", {
--       "query_embedding": [...1536 floats...],
--       "filter_material_family": "aluminum",
--       "filter_part_type": "cnc_milling",
--       "match_count": 5
--   }).execute()

CREATE OR REPLACE FUNCTION rag_search_parts(
    query_embedding         VECTOR(1536),
    filter_material_family  TEXT DEFAULT NULL,
    filter_part_type        TEXT DEFAULT NULL,
    match_count             INTEGER DEFAULT 5
)
RETURNS TABLE (
    part_number       TEXT,
    rev               TEXT,
    material          TEXT,
    material_family   TEXT,
    part_type         TEXT,
    complexity_class  TEXT,
    envelope_mm       TEXT,
    bbox_volume_mm3   NUMERIC,
    stock_form        TEXT,
    n_features        INTEGER,
    n_ops             INTEGER,
    n_tools           INTEGER,
    total_run_min_pc  NUMERIC,
    total_setup_hr    NUMERIC,
    cost_ea_act       NUMERIC,
    unit_price        NUMERIC,
    currency          TEXT,
    description       TEXT,
    operations_json   JSONB,
    jobcost_json      JSONB,
    metadata          JSONB,
    source_md_path    TEXT,
    similarity        REAL
)
LANGUAGE SQL STABLE
AS $$
    SELECT
        p.part_number, p.rev, p.material, p.material_family, p.part_type,
        p.complexity_class, p.envelope_mm, p.bbox_volume_mm3, p.stock_form,
        p.n_features, p.n_ops, p.n_tools,
        p.total_run_min_pc, p.total_setup_hr, p.cost_ea_act, p.unit_price,
        p.currency, p.description, p.operations_json, p.jobcost_json,
        p.metadata, p.source_md_path,
        (1 - (p.description_embedding <=> query_embedding))::REAL AS similarity
    FROM rag_part_embeddings p
    WHERE p.description_embedding IS NOT NULL
      AND (filter_material_family IS NULL OR p.material_family = filter_material_family)
      AND (filter_part_type IS NULL OR p.part_type = filter_part_type)
    ORDER BY p.description_embedding <=> query_embedding
    LIMIT match_count;
$$;


-- ----------------------------------------------------------------------------
-- RPC: rag_search_patterns
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION rag_search_patterns(
    query_embedding   VECTOR(1536),
    match_count       INTEGER DEFAULT 3
)
RETURNS TABLE (
    id              BIGINT,
    kb_path         TEXT,
    section_heading TEXT,
    chunk_order     INTEGER,
    content         TEXT,
    metadata        JSONB,
    similarity      REAL
)
LANGUAGE SQL STABLE
AS $$
    SELECT
        c.id, c.kb_path, c.section_heading, c.chunk_order, c.content, c.metadata,
        (1 - (c.content_embedding <=> query_embedding))::REAL AS similarity
    FROM rag_pattern_chunks c
    WHERE c.content_embedding IS NOT NULL
    ORDER BY c.content_embedding <=> query_embedding
    LIMIT match_count;
$$;
