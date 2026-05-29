-- Migration 004 — dashboard query indexes + planner-column drift cleanup.
--
-- Two unrelated fixes batched together because both target a4_analyses /
-- a4_components and both are no-op on data:
--
-- 1. Add the (user_id, created_at DESC) index that the dashboard list
--    query needs ("show me my analyses, newest first"). Without it,
--    GET /v1/analyses runs a full scan on a4_analyses.
--
-- 2. Drop the phantom columns in the persistence whitelist that don't
--    actually exist in the DB and were silently dropping inserts. After
--    audit (29 May), `bom_part_type` + `pmi_annotations` on a4_components
--    and `tooling_ref` + `machine_ref` on a4_processes were never created
--    by any migration. Add them as JSONB columns so writes succeed (they
--    carry real engine output the FE needs for tool / machine display
--    after the schema flatten).
--
-- All operations are idempotent — re-running this migration is safe.

-- ── 1. Dashboard list index ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_a4_analyses_user_created
    ON a4_analyses (user_id, created_at DESC);

-- The pre-existing idx_a4_analyses_status_created stays — it still helps
-- the operator dashboard ("show me everything currently running").

-- ── 2. Add missing persistence-whitelist columns ───────────────────────────
ALTER TABLE a4_components
    ADD COLUMN IF NOT EXISTS bom_part_type   text,
    ADD COLUMN IF NOT EXISTS pmi_annotations jsonb;

COMMENT ON COLUMN a4_components.bom_part_type IS
    'Part type as declared in the drawing BOM (verbatim string from the BOM '
    'row). Distinct from a4_components.part_type, which is the 3D classifier''s '
    'inference. Useful for auditing BOM-vs-3D classification disagreements.';

COMMENT ON COLUMN a4_components.pmi_annotations IS
    'Product Manufacturing Information from the STEP PMI data — GD&T '
    'callouts attached directly to the 3D geometry. May be empty for parts '
    'that ship dimensions only in the 2D drawing.';

ALTER TABLE a4_processes
    ADD COLUMN IF NOT EXISTS tooling_ref jsonb,
    ADD COLUMN IF NOT EXISTS machine_ref jsonb;

COMMENT ON COLUMN a4_processes.tooling_ref IS
    'DEPRECATED-LEGACY: nested tool reference {tool_id, tool_name, '
    'diameter_mm}. New code emits flat tool_id / tool_name / tool_dimensions '
    'columns instead; this column is kept for back-compat reads only.';

COMMENT ON COLUMN a4_processes.machine_ref IS
    'DEPRECATED-LEGACY: nested machine reference {machine_id, machine_name}. '
    'New code emits flat machine_id / machine_name columns instead; this '
    'column is kept for back-compat reads only.';
