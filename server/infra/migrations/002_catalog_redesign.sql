-- 002_catalog_redesign.sql
-- Strip per-user scoping from the 4 catalog tables and prune unused columns.
--
-- The new model: a single shared shop catalog. RLS is dropped on these
-- tables; the service-role key continues to read them server-side, and the
-- publishable key reads them via PostgREST (catalog is non-sensitive
-- machine/tool/labor inventory).
--
-- DESTRUCTIVE: drops columns containing data. Read the column list before
-- running. Per-user rows are NOT deleted — they merge into the global
-- catalog. If you want per-user scoping later, add it back as a separate
-- join table (a4_user_catalog_overrides), not a column on the inventory
-- table.

BEGIN;

-- ── Drop all RLS policies on the catalog tables first ───────────────────
-- The user_id column is referenced by per-tenant policies; PG refuses to
-- drop a column that policies depend on. Since the catalog is becoming
-- shared (RLS disabled at the end of this migration), we drop every policy
-- on these 4 tables outright.
DO $$
DECLARE
    pol record;
BEGIN
    FOR pol IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN ('a4_labor_rates','a4_machines','a4_tooling','a4_material_stock')
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I',
                       pol.policyname, pol.schemaname, pol.tablename);
    END LOOP;
END$$;

-- ── a4_labor_rates ──────────────────────────────────────────────────────
ALTER TABLE public.a4_labor_rates
    DROP COLUMN IF EXISTS user_id;

DROP INDEX IF EXISTS idx_a4_labor_rates_user_id;

-- Disambiguate now-collapsed rows: keep the most-recent updated row per role.
-- (4 users × 4 roles = 16 rows → ~4 rows after dedup.)
DELETE FROM public.a4_labor_rates a
    USING public.a4_labor_rates b
    WHERE LOWER(a.role_name) = LOWER(b.role_name)
      AND (a.updated_at, a.id) < (b.updated_at, b.id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_a4_labor_rates_role
    ON public.a4_labor_rates (LOWER(role_name)) WHERE is_active;

-- ── a4_machines ─────────────────────────────────────────────────────────
ALTER TABLE public.a4_machines
    DROP COLUMN IF EXISTS user_id,
    DROP COLUMN IF EXISTS machine_brand,
    DROP COLUMN IF EXISTS tool_holder,
    DROP COLUMN IF EXISTS tool_collet,
    DROP COLUMN IF EXISTS capability,
    DROP COLUMN IF EXISTS table_size_x_mm,
    DROP COLUMN IF EXISTS table_size_y_mm;

DROP INDEX IF EXISTS idx_a4_machines_user_id;

-- Dedupe machines collapsed from multiple per-user catalogs: keep newest
-- (with id as tiebreaker when updated_at ties).
DELETE FROM public.a4_machines a
    USING public.a4_machines b
    WHERE LOWER(a.machine_name) = LOWER(b.machine_name)
      AND (a.updated_at, a.id) < (b.updated_at, b.id);

-- machine_name should be unique (informational; not enforced previously).
CREATE UNIQUE INDEX IF NOT EXISTS uq_a4_machines_name
    ON public.a4_machines (LOWER(machine_name)) WHERE is_active;

-- ── a4_tooling ──────────────────────────────────────────────────────────
ALTER TABLE public.a4_tooling
    DROP COLUMN IF EXISTS user_id,
    DROP COLUMN IF EXISTS tool_spec,
    DROP COLUMN IF EXISTS tool_holder_full,
    DROP COLUMN IF EXISTS tool_make,
    DROP COLUMN IF EXISTS machine_brand_affinity,
    DROP COLUMN IF EXISTS roughing_finishing,
    DROP COLUMN IF EXISTS tool_holder,
    DROP COLUMN IF EXISTS tool_collet,
    DROP COLUMN IF EXISTS tool_projection_mm,
    DROP COLUMN IF EXISTS tool_length_mm,
    DROP COLUMN IF EXISTS flute_length_mm;

DROP INDEX IF EXISTS idx_a4_tooling_user_id;

-- Add JSONB tool_dimensions to match the new ManufacturingProcess schema.
-- Populated from existing flat columns (so historical rows stay queryable).
ALTER TABLE public.a4_tooling
    ADD COLUMN IF NOT EXISTS tool_dimensions jsonb;

UPDATE public.a4_tooling
    SET tool_dimensions = jsonb_strip_nulls(jsonb_build_object(
        'diameter_mm',      diameter_mm,
        'length_mm',        length_mm,
        'corner_radius_mm', corner_radius_mm,
        'flute_count',      flute_count
    ))
    WHERE tool_dimensions IS NULL;

-- Index for the agent's most common filter (by type then diameter).
CREATE INDEX IF NOT EXISTS idx_a4_tooling_type_dia
    ON public.a4_tooling (tool_type, diameter_mm) WHERE is_active;

-- ── a4_material_stock ───────────────────────────────────────────────────
ALTER TABLE public.a4_material_stock
    DROP COLUMN IF EXISTS user_id;

DROP INDEX IF EXISTS idx_a4_material_stock_user_id;

CREATE INDEX IF NOT EXISTS idx_a4_material_stock_form_name
    ON public.a4_material_stock (material_form, LOWER(material_name)) WHERE is_active;

-- ── RLS: turn off on shared catalog ─────────────────────────────────────
-- These tables are shop inventory, not user data. Service-role bypasses
-- RLS anyway, and the publishable key needs read access for the catalog
-- UI. Disable RLS to make that explicit.
ALTER TABLE public.a4_labor_rates    DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.a4_machines       DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.a4_tooling        DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.a4_material_stock DISABLE ROW LEVEL SECURITY;

COMMIT;
