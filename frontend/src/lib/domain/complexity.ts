/**
 * Per-component machining complexity — derived from features on the wire
 * Component object (no backend field ever sets a component/op `complexity`).
 *
 * Shared by manufacturing-plan.tsx (header badge + stats strip) and
 * cost-model.ts (Cycle-Time table Complexity column + cost-breakdown header
 * badge) so both surfaces show the same band.
 */
import type { Component } from "@/lib/api/types";

export interface Complexity {
  nFeatures: number;
  nTight: number;
  nThreads: number;
  nGdt: number;
  band: "Low" | "Medium" | "High";
}

/** A feature counts as "tight" when its total tolerance band ≤ 0.05 mm
 *  (≈ ±0.001"), or dim_tagger tagged it tight/ground. */
export function isTight(f: {
  tolerance_plus?: number | null;
  tolerance_minus?: number | null;
  tolerance_class?: unknown;
}): boolean {
  const cls = typeof f.tolerance_class === "string" ? f.tolerance_class.toLowerCase() : "";
  if (cls === "tight" || cls === "ground") return true;
  const tp = typeof f.tolerance_plus === "number" ? Math.abs(f.tolerance_plus) : null;
  const tm = typeof f.tolerance_minus === "number" ? Math.abs(f.tolerance_minus) : null;
  const band = (tp ?? 0) + (tm ?? 0);
  return band > 0 && band <= 0.05;
}

export function deriveComplexity(c: Component): Complexity {
  const feats = c.features ?? [];
  const nFeatures = feats.reduce((a, f) => a + (f.count && f.count > 1 ? f.count : 1), 0);
  const nTight = feats.filter(isTight).length;
  const nThreads = feats.filter(
    (f) => f.is_threaded || typeof f.thread_spec === "string",
  ).length;
  const nGdt = feats.reduce((a, f) => a + ((f.gdt_callouts ?? []).length), 0);
  // Simple, honest heuristic — not a fake /10 score.
  const score = nFeatures * 0.3 + nTight * 1.2 + nThreads * 1.0 + nGdt * 0.8;
  const band: Complexity["band"] = score >= 8 ? "High" : score >= 3.5 ? "Medium" : "Low";
  return { nFeatures, nTight, nThreads, nGdt, band };
}
