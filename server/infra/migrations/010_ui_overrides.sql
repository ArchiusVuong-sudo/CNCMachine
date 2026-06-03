-- 010_ui_overrides.sql
-- Inline user corrections to a saved run's Bill-of-Material rows.
--
-- The BoM inline editor (double-click a cell) persists display overrides here;
-- the frontend applies them on top of the computed row when rendering. Part
-- Information edits write straight to a4_2d_extraction columns and need no new
-- column. Keeping overrides in one JSON blob avoids a column per editable field
-- and lets the editor cover every BoM column uniformly.

ALTER TABLE a4_components
    ADD COLUMN IF NOT EXISTS ui_overrides jsonb;
