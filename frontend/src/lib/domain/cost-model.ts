/**
 * Cost Breakdown edit model — the editable, per-row shape the Cycle Time /
 * Cost Breakdown panel binds to, plus the pure builders and reducers that
 * derive it from a `Component` (or the level-0 assembly aggregate) and project
 * it back to a numeric feedback payload.
 *
 * Pure: builders take data and return data; the React state machine that owns
 * a live `EditModel` lives in `useCostBreakdown`.
 */
import type { Component } from "@/lib/api/types";
import { num, toNum } from "@/lib/format";
import { isUuid } from "@/lib/utils";
import { rowsFromComponent } from "./selectors";
import { deriveComplexity } from "./complexity";

/** Which of the two merged tables (cost vs. cycle time) is shown. */
export type CostView = "cost" | "cycle";

/** One editable process/routing row. */
export interface EditRow {
  id: string;
  process: string;
  /** Component label rendered as a small badge in the assembly view; absent
   *  for single-component models so the row doesn't repeat the header. */
  compTag?: string;
  opCode?: string;
  machine?: string;
  /** Cost category from the backend routing row: 'machining' | 'deburring' |
   *  'inspection' | 'hole_making' | 'finishing' | … Absent on legacy rows. */
  category?: string;
  complexity: string;
  cycleMin: string;
  laborUsd: string;
  burdenUsd: string;
  toolUsd: string;
}

/** The whole editable model for one component (or the assembly aggregate). */
export interface EditModel {
  materialUsd: string;
  setupUsd: string;
  deburrUsd: string;
  inspectionUsd: string;
  /** Setup time (min/lot) — shown in the Cycle-Time view's Setup cell. */
  setupMin: string;
  rows: EditRow[];
}

/** Routing rows → editable rows. `prefix` tags each row with the component name
 *  (used by the assembly aggregate so rows stay attributable). Machine field
 *  drops the raw `machine_id` UUID fallback — it leaks into the UI as a long
 *  hex string and breaks table layouts. Reads the new flat Pydantic shape
 *  (`machine_name`) first and the legacy nested `machine_ref` as a back-compat
 *  fallback for runs persisted before the schema flatten. */
export function rowsForComponent(comp: Component, prefix = false): EditRow[] {
  // Derive once per component — all rows share the component-level band (no
  // per-op complexity exists in the data model).
  const complexityBand = deriveComplexity(comp).band;
  return rowsFromComponent(comp).map((p, i): EditRow => {
    const machineName =
      p.machine_name ??
      (p as { machine_ref?: { machine_name?: string } }).machine_ref?.machine_name;
    return {
      id: `${comp.component_index}-${p.op_code ?? p.op_id ?? i}-${i}`,
      process: String(p.process_type ?? p.category ?? p.op_code ?? `Process ${i + 1}`),
      compTag: prefix ? (comp.name ?? `Comp ${comp.component_index}`) : undefined,
      opCode: p.op_code,
      machine: machineName && !isUuid(machineName) ? machineName : undefined,
      category: p.category ?? undefined,
      complexity: p.complexity != null ? String(p.complexity) : complexityBand,
      cycleMin: num(p.cycle_time_min) || "0",
      laborUsd: num(p.labor_cost_usd, 4) || "0",
      burdenUsd: num(p.machine_cost_usd, 4) || "0",
      toolUsd: num(p.tool_cost_usd, 4) || "0",
    };
  });
}

/** Single-component edit model. */
export function buildComponentModel(comp: Component): EditModel {
  const cost = comp.cost ?? {};
  return {
    materialUsd: num(cost.raw_material_usd, 4) || "0",
    setupUsd: num(cost.setup_usd, 4) || "0",
    deburrUsd: num(cost.deburr_usd, 4) || "0",
    inspectionUsd: num(cost.inspection_usd, 4) || "0",
    setupMin: num(cost.setup_min_per_lot, 2) || "0",
    rows: rowsForComponent(comp),
  };
}

/** Assembly aggregate (level-0) model — every component's rows + summed lines. */
export function buildAssemblyModel(components: Component[]): EditModel {
  const sum = (sel: (c: Component) => unknown) =>
    components.reduce((a, c) => a + toNum(num(sel(c) as number, 4)), 0);
  return {
    materialUsd: String(sum((c) => c.cost?.raw_material_usd)),
    setupUsd: String(sum((c) => c.cost?.setup_usd)),
    deburrUsd: String(sum((c) => c.cost?.deburr_usd)),
    inspectionUsd: String(sum((c) => c.cost?.inspection_usd)),
    setupMin: String(sum((c) => c.cost?.setup_min_per_lot)),
    rows: components.flatMap((c) => rowsForComponent(c, true)),
  };
}

export const rowTotal = (r: EditRow): number => toNum(r.laborUsd) + toNum(r.burdenUsd) + toNum(r.toolUsd);

/** Classify a row's display bucket. Rows whose category is 'deburring' or
 *  'inspection' flow into those buckets; everything else (machining,
 *  hole_making, finishing, admin, …) stays in Machining. cost_engine bills
 *  DEBUR + INSPECT op rows into machining_total (deburr_usd=0 by design), so
 *  moving them to their visual buckets here changes NO total — it just labels
 *  the money correctly instead of hiding deburr/per-part inspection in
 *  "Machining". */
function rowBucket(r: EditRow): "machining" | "deburring" | "inspection" {
  const cat = (r.category ?? "").toLowerCase();
  if (cat === "deburring") return "deburring";
  if (cat === "inspection") return "inspection";
  return "machining";
}

export function deriveTotals(m: EditModel) {
  let machining = 0, deburrRows = 0, inspectionRows = 0, cycle = 0;
  // Per-bucket cycle minutes — feed the Cycle-Time view's summary cells.
  let machiningMin = 0, deburrMin = 0, inspectionMin = 0;
  for (const r of m.rows) {
    const cost = rowTotal(r);
    const min = toNum(r.cycleMin);
    const bucket = rowBucket(r);
    if (bucket === "deburring") { deburrRows += cost; deburrMin += min; }
    else if (bucket === "inspection") { inspectionRows += cost; inspectionMin += min; }
    else { machining += cost; machiningMin += min; }
    cycle += min;
  }
  // Add the backend scalar buckets (deburr_usd=0 / inspection_usd=lot-inspection)
  // on top of the op-row subtotals so each display line is complete.
  const deburr = deburrRows + toNum(m.deburrUsd);
  const inspection = inspectionRows + toNum(m.inspectionUsd);
  const total = toNum(m.materialUsd) + toNum(m.setupUsd) + machining + deburr + inspection;
  return { machining, deburr, inspection, cycle, total, machiningMin, deburrMin, inspectionMin };
}

/** Project the edit model back to the numeric shape the feedback endpoint wants. */
export function toNumericPayload(m: EditModel) {
  const { machining, cycle, total } = deriveTotals(m);
  return {
    raw_material_usd: toNum(m.materialUsd),
    setup_usd: toNum(m.setupUsd),
    deburr_usd: toNum(m.deburrUsd),
    inspection_usd: toNum(m.inspectionUsd),
    machining_total_usd: Number(machining.toFixed(4)),
    total_usd: Number(total.toFixed(4)),
    total_cycle_min: Number(cycle.toFixed(4)),
    processes: m.rows.map((r) => ({
      process_type: r.process,
      op_code: r.opCode,
      complexity: r.complexity || undefined,
      cycle_time_min: toNum(r.cycleMin),
      labor_cost_usd: toNum(r.laborUsd),
      machine_cost_usd: toNum(r.burdenUsd),
      tool_cost_usd: toNum(r.toolUsd),
      total_cost_usd: Number(rowTotal(r).toFixed(4)),
    })),
  };
}
