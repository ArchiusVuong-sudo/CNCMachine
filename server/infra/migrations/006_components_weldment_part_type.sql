-- Migration 006 — allow 'weldment' in a4_components.part_type.
--
-- The PartType enum gained WELDMENT (multi-body welded / solvent-bonded
-- assembly). The synthetic top-of-assembly node that carries the whole
-- weldment's routing is persisted with part_type 'weldment'. The old CHECK
-- constraint rejected it, which (combined with a uuid-FK bug) silently
-- dropped the assembly_top component and all of its routing rows from the DB.
--
-- Rebuild the CHECK to include 'weldment'. Idempotent — safe to re-run.

ALTER TABLE public.a4_components
    DROP CONSTRAINT IF EXISTS a4_components_part_type_check;

ALTER TABLE public.a4_components
    ADD CONSTRAINT a4_components_part_type_check
    CHECK (part_type = ANY (ARRAY[
        'sheet_metal'::text,
        'cnc_milling'::text,
        'cnc_lathe'::text,
        'cnc_lathe_milling'::text,
        'tube_pipe'::text,
        'hardware'::text,
        'weldment'::text,
        'unknown'::text
    ]));
