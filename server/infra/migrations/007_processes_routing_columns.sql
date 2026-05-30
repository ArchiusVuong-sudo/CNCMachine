-- Migration 007 — add routing-agent columns to a4_processes.
--
-- The routing rows the agent emits carry op_code / description / tool_type /
-- operation_type, but the persistence whitelist + table lacked these columns,
-- so they were silently dropped from a4_processes (the data still reaches the
-- SSE final_answer + UI, but a DB query of the routing was incomplete).
--
-- Idempotent — safe to re-run.

ALTER TABLE public.a4_processes
    ADD COLUMN IF NOT EXISTS op_code        text,
    ADD COLUMN IF NOT EXISTS description    text,
    ADD COLUMN IF NOT EXISTS tool_type      text,
    ADD COLUMN IF NOT EXISTS operation_type text;

COMMENT ON COLUMN public.a4_processes.op_code IS
    'Operation code from the routing agent (e.g. CNCM_PROFILE_HOLES, ASSY_WELD_PVC).';
COMMENT ON COLUMN public.a4_processes.description IS
    'Human-readable operation description from the routing agent.';
COMMENT ON COLUMN public.a4_processes.tool_type IS
    'Primary tool family/type for the operation (e.g. end_mill, drill, tap).';
COMMENT ON COLUMN public.a4_processes.operation_type IS
    'Operation type/category from the routing agent (e.g. roughing, finishing).';
