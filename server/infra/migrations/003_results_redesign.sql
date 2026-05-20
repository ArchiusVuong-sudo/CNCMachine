-- 003_results_redesign.sql
-- Reshape the result tables so the rebuilt server can persist its actual
-- output. After this, the pipeline's natural shape (Pydantic models in
-- core/schemas/) maps 1:1 onto Postgres columns.
--
-- Tables touched:
--   - a4_analyses       : minor column adds
--   - a4_components     : add agentic outputs, keep stock_json
--   - a4_features       : replace face_ids int[] with key_face_ids text[],
--                         add feature_id text (agent's "F1", "F2")
--   - a4_processes      : feature_ids → text[], add agent_phase_outputs jsonb
--   - a4_gcode          : repurposed; one row per .nc file (was: per component)
--   - a4_cam_runs       : new — top-level CAM run record
--   - a4_feedback       : new — mirrors KNOWLEDGE_BASE/_research/feedback/
--
-- WARNING: a4_features.face_ids and a4_processes.feature_ids hold UUID/int
-- arrays today. The migration creates the new columns alongside, copies
-- what it can, then drops the legacy columns. Backfills are best-effort
-- (face_ids has no hash to recover key_face_id, so legacy rows get
-- empty arrays; new rows will populate correctly).

BEGIN;

-- ── a4_analyses ─────────────────────────────────────────────────────────
-- Already lean after migration 001. Add the few missing bits the new
-- orchestrator wants to record.
ALTER TABLE public.a4_analyses
    ADD COLUMN IF NOT EXISTS trace_json     jsonb,        -- core/tracing.py output
    ADD COLUMN IF NOT EXISTS cam_run_id     uuid;         -- FK → a4_cam_runs (set later)

CREATE INDEX IF NOT EXISTS idx_a4_analyses_status_created
    ON public.a4_analyses (status, created_at DESC);

-- ── a4_components ───────────────────────────────────────────────────────
-- Add per-component agentic plan (Phase A/B/C/D outputs) and routing rows.
-- These were previously stored separately in a4_processes; we keep
-- a4_processes for the cost-row breakdown but also snapshot the agent
-- output here for quick UI render.
ALTER TABLE public.a4_components
    ADD COLUMN IF NOT EXISTS agentic_plan     jsonb,    -- ProcessPlan dump
    ADD COLUMN IF NOT EXISTS chosen_machine_id uuid REFERENCES public.a4_machines(id),
    ADD COLUMN IF NOT EXISTS machine_class    text,     -- 'mill_3axis', 'lathe', ...
    DROP COLUMN IF EXISTS kb_evidence;                  -- old shadow-mode field

CREATE INDEX IF NOT EXISTS idx_a4_components_analysis
    ON public.a4_components (analysis_id, component_index);

-- ── a4_features ─────────────────────────────────────────────────────────
-- Rebuild face/feature identification on top of the new geometric-hash
-- format. The old int[] face_ids only made sense within one FreeCAD
-- session; key_face_ids survive STEP re-imports because they include
-- a SHA hash of the face's geometry.
ALTER TABLE public.a4_features
    ADD COLUMN IF NOT EXISTS feature_id     text,                -- agent's "F1", "F2", ...
    ADD COLUMN IF NOT EXISTS key_face_ids   text[] DEFAULT '{}'; -- "Face42_<hash>"[]

UPDATE public.a4_features
    SET feature_id = 'F' || feature_index::text
    WHERE feature_id IS NULL;

ALTER TABLE public.a4_features
    DROP COLUMN IF EXISTS face_ids;     -- int[] FreeCAD indices — obsolete

CREATE INDEX IF NOT EXISTS idx_a4_features_component
    ON public.a4_features (component_id, feature_index);
CREATE INDEX IF NOT EXISTS idx_a4_features_type
    ON public.a4_features (feature_type);

-- ── a4_processes ────────────────────────────────────────────────────────
-- The wire shape is dominated by the agent's per-op output. Drop the
-- two competing feature_id columns and replace with a single text[]
-- (agent feature IDs like "F1").
ALTER TABLE public.a4_processes
    ADD COLUMN IF NOT EXISTS feature_ids_text  text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS agent_phase       text,   -- 'A' | 'B' | 'C' | 'D'
    ADD COLUMN IF NOT EXISTS tool_dimensions   jsonb,
    ADD COLUMN IF NOT EXISTS feeds_speeds      jsonb;  -- {spindle_rpm, feed_mm_min, doc_mm, woc_mm}

-- Best-effort backfill: if feature_indices is populated, use it.
UPDATE public.a4_processes
    SET feature_ids_text = ARRAY(SELECT 'F' || x::text FROM unnest(feature_indices) x)
    WHERE coalesce(array_length(feature_ids_text, 1), 0) = 0
      AND coalesce(array_length(feature_indices, 1), 0) > 0;

ALTER TABLE public.a4_processes
    DROP COLUMN IF EXISTS feature_ids,        -- uuid[]  (legacy)
    DROP COLUMN IF EXISTS feature_indices;    -- int[]   (legacy)

ALTER TABLE public.a4_processes
    RENAME COLUMN feature_ids_text TO feature_ids;

CREATE INDEX IF NOT EXISTS idx_a4_processes_component_seq
    ON public.a4_processes (component_id, sequence_order);

-- ── a4_cam_runs (new) ───────────────────────────────────────────────────
-- One row per CAM run (either inline in the SSE pipeline or via POST
-- /v1/generate-gcode). Mirrors CAMOutput in server/engines/cam/engine.py.
CREATE TABLE IF NOT EXISTS public.a4_cam_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       timestamptz NOT NULL DEFAULT now(),
    analysis_id      uuid REFERENCES public.a4_analyses(id) ON DELETE CASCADE,
    runs_dir         text NOT NULL,             -- e.g. runs/<analysis_id>/
    ok               boolean NOT NULL DEFAULT false,
    total_files      integer NOT NULL DEFAULT 0,
    elapsed_seconds  numeric,
    error            text,
    post_processor   text DEFAULT 'linuxcnc'
);

CREATE INDEX IF NOT EXISTS idx_a4_cam_runs_analysis
    ON public.a4_cam_runs (analysis_id);

-- ── a4_gcode (repurposed) ───────────────────────────────────────────────
-- Was: one row per component, single gcode_text dump.
-- Now: one row per .nc file emitted by the CAM engine. Bound to a cam_run
-- (and through it, an analysis); the legacy gcode_text/component_id link
-- stays so the dashboard can still render the per-component gcode bundle.
ALTER TABLE public.a4_gcode
    ADD COLUMN IF NOT EXISTS cam_run_id  uuid REFERENCES public.a4_cam_runs(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS sequence    integer,
    ADD COLUMN IF NOT EXISTS op_code     text,
    ADD COLUMN IF NOT EXISTS nc_file_path text,
    ADD COLUMN IF NOT EXISTS size_bytes  integer;

-- legacy `mode` was a free-form descriptor of the previous engine
-- (full_path_workbench / hardware_purchased / fallback_gcode_generator);
-- the new CAM engine doesn't emit it.
ALTER TABLE public.a4_gcode DROP COLUMN IF EXISTS mode;

CREATE INDEX IF NOT EXISTS idx_a4_gcode_run_seq
    ON public.a4_gcode (cam_run_id, sequence);

-- ── a4_feedback (new) ───────────────────────────────────────────────────
-- Operator feedback today goes only to KNOWLEDGE_BASE/_research/feedback/.
-- Mirror to DB so dashboards can list it without filesystem access.
-- Server still writes the markdown — this row is a pointer.
CREATE TABLE IF NOT EXISTS public.a4_feedback (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at       timestamptz NOT NULL DEFAULT now(),
    analysis_id      uuid REFERENCES public.a4_analyses(id) ON DELETE CASCADE,
    component_index  integer,
    feedback_text    text NOT NULL,
    file_path        text,                       -- relative to KNOWLEDGE_BASE/
    created_by       uuid,
    applied_to_kb_at timestamptz                 -- nullable; set when the agent picks it up
);

CREATE INDEX IF NOT EXISTS idx_a4_feedback_analysis
    ON public.a4_feedback (analysis_id, created_at DESC);

-- ── Wire the FK now that a4_cam_runs exists ─────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_a4_analyses_cam_run'
    ) THEN
        ALTER TABLE public.a4_analyses
            ADD CONSTRAINT fk_a4_analyses_cam_run
            FOREIGN KEY (cam_run_id) REFERENCES public.a4_cam_runs(id) ON DELETE SET NULL;
    END IF;
END$$;

COMMIT;
