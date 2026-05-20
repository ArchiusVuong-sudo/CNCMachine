-- 001_drop_obsolete.sql
-- Drop tables/columns the rebuilt server no longer uses.
--
-- Run order: 001 → 002 → 003. Each migration is idempotent.
-- Apply with: psql "$DATABASE_URL" -f infra/migrations/001_drop_obsolete.sql
-- (or paste into Supabase SQL editor).

BEGIN;

-- ── kb_shadow_runs: A/B comparison between legacy planner and KB agent. ─
-- The rebuilt server is "agent only, no fallback" so there is no legacy
-- planner to compare against. Live row count is 0.
DROP TABLE IF EXISTS public.kb_shadow_runs;

-- ── a4_analyses: drop the legacy review-workflow columns. ───────────────
-- Operator feedback now flows through POST /v1/feedback → writeback under
-- KNOWLEDGE_BASE/_research/feedback/<analysis_id>/*.md. These columns are
-- dead.
ALTER TABLE public.a4_analyses
    DROP COLUMN IF EXISTS kb_review_status,
    DROP COLUMN IF EXISTS kb_review_notes,
    DROP COLUMN IF EXISTS kb_reviewed_at,
    DROP COLUMN IF EXISTS kb_reviewed_by,
    DROP COLUMN IF EXISTS kb_engine_mode;

-- ── RPC: copy_a4_defaults_to_user. ──────────────────────────────────────
-- Catalog is single-tenant now (no user_id scoping), so per-user seeding
-- is meaningless.
DROP FUNCTION IF EXISTS public.copy_a4_defaults_to_user(uuid);
DROP FUNCTION IF EXISTS public.copy_a4_defaults_to_user();

COMMIT;
