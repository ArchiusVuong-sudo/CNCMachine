/**
 * Results adapter — turns a raw `FinalAnswer` envelope into the costed
 * components and headline totals the estimate layout renders.
 *
 * The backend stamps per-op USD onto the top-level `processes_per_component`
 * (consolidation-aware, costed) while each component's `manufacturing_processes`
 * is the pre-consolidation, uncosted projection. We adopt the costed rows onto
 * each component (aligned by position) so the BOM and breakdown read real money
 * and a consolidated solid shows an empty routing instead of a stale $0 one.
 */
import type { Component, FinalAnswer, VlmExtraction } from "@/lib/api/types";
import { componentCycleMin } from "./selectors";

/** First non-empty trimmed string among the candidates. */
export function firstStr(...vals: (string | null | undefined)[]): string | undefined {
  for (const v of vals) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return undefined;
}

/** Page-header title: Part Number (+ Revision), else the supplied fallback. */
export function headerTitle(vlm: VlmExtraction | null | undefined, fallback: string): string {
  const pn = firstStr(vlm?.part_number, vlm?.title_block?.part_number);
  const rev = firstStr(vlm?.revision, vlm?.title_block?.revision);
  if (pn) return rev ? `${pn} · Rev ${rev}` : pn;
  return fallback;
}

/** Adopt the costed `processes_per_component` rows onto each component. */
export function adoptCostedComponents(results: FinalAnswer | null): Component[] {
  const base = results?.components ?? [];
  const ppc = results?.processes_per_component;
  if (!Array.isArray(ppc)) return base;
  return base.map((c, i) =>
    Array.isArray(ppc[i]) ? { ...c, manufacturing_processes: ppc[i] } : c,
  );
}

export interface ResultTotals {
  totalUsd?: number;
  totalMin: number;
  assemblyName?: string;
}

/**
 * Headline totals for an estimate. The backend currently emits
 * `total_minutes = 0`, so we fall back to the summed per-component cycle
 * (consolidation-aware via `componentCycleMin`) to keep the headline non-zero.
 */
export function deriveResultTotals(results: FinalAnswer | null, components: Component[]): ResultTotals {
  const totalUsd = results?.total_usd ?? results?.cost?.total_usd;
  const rawTotalMin = results?.total_minutes ?? results?.cycle_time?.total_minutes;
  const totalMin =
    typeof rawTotalMin === "number" && rawTotalMin > 0
      ? rawTotalMin
      : components.reduce((a, c) => a + componentCycleMin(c), 0);
  const assemblyName = firstStr(results?.assembly_name, results?.file_name);
  return { totalUsd, totalMin, assemblyName };
}
