-- Migration 009 — persist dim_tagger feature enrichment + component GD&T.
--
-- dim_tagger.py sets these on feature/component dicts at runtime, but there were
-- no columns for them, so _filter() silently dropped them on every insert. The
-- live SSE run carried them (Component/Feature use extra="allow"), but a
-- saved-run reload served features/components missing them — so the Feature Map
-- (Tolerance class / Thread / Operations), the Threads tab, and the per-component
-- GD&T tab rendered blank on reload.
--
-- Idempotent — safe to re-run.

ALTER TABLE public.a4_features
    ADD COLUMN IF NOT EXISTS tolerance_class text,
    ADD COLUMN IF NOT EXISTS is_threaded     boolean,
    ADD COLUMN IF NOT EXISTS thread_spec     text,
    ADD COLUMN IF NOT EXISTS operations      text[] DEFAULT '{}';

COMMENT ON COLUMN public.a4_features.tolerance_class IS
    'Tightest tolerance band dim_tagger assigned: ground | tight | standard | rough | loose.';
COMMENT ON COLUMN public.a4_features.is_threaded IS
    'True when dim_tagger matched a thread spec to this feature by minor-diameter lookup.';
COMMENT ON COLUMN public.a4_features.thread_spec IS
    'Raw thread spec (e.g. M6, 1/4-20) when is_threaded is true.';
COMMENT ON COLUMN public.a4_features.operations IS
    'Operations implied by dim_tagger (e.g. {tapping}); text array.';

ALTER TABLE public.a4_components
    ADD COLUMN IF NOT EXISTS gdt_callouts text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.a4_components.gdt_callouts IS
    'Drawing-level GD&T callout strings dim_tagger could not pin to a specific 3D '
    'feature (position/flatness/parallelism). Read by the FE componentGdt() fallback. '
    'Distinct from pmi_annotations (3D STEP PMI objects).';
