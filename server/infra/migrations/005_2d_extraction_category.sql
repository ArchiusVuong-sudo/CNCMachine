-- Migration 005 — persist drawing-level part_category + assembly_method.
--
-- Engine 1 (2D VLM) now emits two routing-critical drawing-level fields that
-- the brief (Page 3 OCR outputs) requires: `part_category`
-- (weldment / assembly_bolted / assembly_bonded / sheet_metal / cnc_milling /
-- ...) and `assembly_method` (welded / bolted / riveted / bonded). They drive
-- whether Engine 3 plans ASSY_WELD_* / ASSY_SOLVENT_BOND / ASSY_HARDWARE_INSTALL
-- on the top assembly node.
--
-- Before this migration the persistence whitelist silently dropped them, so a
-- re-query of a saved run returned NULL. Add the columns so they survive.
-- The persistence layer upserts these via a tolerant fallback, so writes
-- still succeed even if this migration has not yet been applied.
--
-- Idempotent — safe to re-run.

ALTER TABLE public.a4_2d_extraction
    ADD COLUMN IF NOT EXISTS part_category   text,
    ADD COLUMN IF NOT EXISTS assembly_method text;

COMMENT ON COLUMN public.a4_2d_extraction.part_category IS
    'Drawing-level part family: weldment | assembly_bolted | assembly_bonded | sheet_metal | cnc_milling | ... (Engine 1 OCR output, may be refined by AFR cross-feed).';
COMMENT ON COLUMN public.a4_2d_extraction.assembly_method IS
    'Drawing mfg spec: welded | bolted | riveted | bonded | null (Engine 1 OCR output).';
