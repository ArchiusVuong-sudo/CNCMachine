-- Migration 008 — store the saved-run activity log on a4_analyses.
--
-- The history view's "pipeline activity" card replays the SSE event log
-- (phase updates, agent thinking, warnings). That log used to be appended
-- only to the local file KNOWLEDGE_BASE/_research/notes/<id>_full.json, so it
-- never survived a redeploy to a different host. History is now DB-only
-- (server/infra/analyses_repo.py), so the log moves into the row it belongs to.
--
-- Idempotent — safe to re-run.

ALTER TABLE public.a4_analyses
    ADD COLUMN IF NOT EXISTS messages_json jsonb;

COMMENT ON COLUMN public.a4_analyses.messages_json IS
    'Captured SSE event log for the run ([{id,type,data,timestamp}, ...]); '
    'replayed by the saved-run pipeline-activity card. Written best-effort '
    'after the stream completes (server/api/routes/analyze.py).';
