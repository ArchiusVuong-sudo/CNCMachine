/**
 * Pure per-component selectors — the domain layer's read model.
 *
 * Everything that turns a raw wire `Component` into a number the UI shows
 * lives here, so the Bill of Material, the Cost Breakdown, and the assembly
 * totals all agree by construction. No React, no JSX — just data in, data out.
 */
import type { Component, RoutingRow } from "@/lib/api/types";

/** Routing/cost rows for a component, tolerating the legacy field name. */
export function rowsFromComponent(comp: Component): RoutingRow[] {
  return comp.manufacturing_processes ?? comp.processes ?? [];
}

const n = (v: unknown): number => (typeof v === "number" && isFinite(v) ? v : 0);

/** Labor + machine burden + tooling for one routing row. */
export function rowMachiningUsd(r: RoutingRow): number {
  return n(r.labor_cost_usd) + n(r.machine_cost_usd) + n(r.tool_cost_usd);
}

/** Primary machine for a component (first routing row that names one). */
export function componentMachine(comp: Component): string | undefined {
  for (const r of rowsFromComponent(comp)) {
    // Pydantic emits flat `machine_name`; old runs may have nested `machine_ref`.
    const name = r.machine_name ?? (r as { machine_ref?: { machine_name?: string } }).machine_ref?.machine_name;
    if (name) return name;
  }
  const planner = comp.planner ?? comp.agentic;
  const ranked = planner?.ranked_machines ?? planner?.top_machines ?? [];
  return ranked[0]?.machine_name;
}

/** Total cycle minutes: explicit field, else summed rows, else agentic run time. */
export function componentCycleMin(comp: Component): number {
  // A consolidated solid contributes its machining to the assembly owner, not
  // itself — counting its agentic run time again would double the assembly cycle.
  if ((comp.planner ?? comp.agentic)?.suppressed_by_consolidation_gate) return 0;
  if (typeof comp.cycle_time_min === "number" && isFinite(comp.cycle_time_min)) return comp.cycle_time_min;
  const summed = rowsFromComponent(comp).reduce((acc, r) => acc + n(r.cycle_time_min), 0);
  if (summed > 0) return summed;
  return n((comp.planner ?? comp.agentic)?.total_run_min_per_part);
}

export function componentMaterialUsd(comp: Component): number {
  return n(comp.cost?.raw_material_usd);
}

/** Machining (process) cost: summed routing rows, else the by-process map. */
export function componentProcessUsd(comp: Component): number {
  const rows = rowsFromComponent(comp);
  const summed = rows.reduce((acc, r) => acc + rowMachiningUsd(r), 0);
  if (summed > 0) return summed;
  const byProc = comp.cost?.machining_usd_by_process ?? {};
  return Object.values(byProc).reduce((acc: number, v) => acc + n(v), 0);
}

/** Total component cost: explicit field, else summed pieces. */
export function componentTotalUsd(comp: Component): number {
  const explicit = comp.cost?.total_usd;
  if (typeof explicit === "number" && isFinite(explicit)) return explicit;
  const c = comp.cost ?? {};
  return (
    componentMaterialUsd(comp) +
    n(c.setup_usd) +
    componentProcessUsd(comp) +
    n(c.deburr_usd) +
    n(c.inspection_usd)
  );
}
