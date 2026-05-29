/**
 * Per-component projections of the drawing-level extraction.
 *
 * The 2D VLM extraction (`vlm_extraction.dimensions / gdt_callouts / threads`)
 * is a flat list scoped to the whole drawing — entries aren't tagged with a
 * component id. To honour the 28 May review ("Tolerances/GD&T/Threads should
 * reflect only the selected component") we synthesise the per-component view
 * from the component's `features[]` instead, which IS scoped:
 *
 *   - tolerances → features that carry `tolerance_plus` / `tolerance_minus`
 *   - GD&T       → features that carry `gdt_callouts[]`
 *   - threads    → features whose `feature_type` matches a thread pattern,
 *                  or that carry a `thread_pitch_mm` dimension
 *
 * When nothing is selected (the level-0 Assembly row) we fall back to the
 * drawing-level extraction so the operator can still see everything the VLM
 * read off the drawing.
 */
import type {
  Component,
  DimensionRow,
  Feature,
  GdtCallout,
  ThreadSpec,
  VlmExtraction,
} from "@/lib/api/types";

const THREAD_RE = /thread/i;

/** A reasonable headline dimension for a feature, for the Tolerances "Nominal" column. */
function featureNominal(f: Feature): number | undefined {
  const d = f.dimensions ?? {};
  return d.diameter_mm ?? d.depth_mm ?? d.length_mm ?? d.width_mm ?? d.radius_mm;
}

function prettyFeatureLabel(f: Feature): string {
  const base = (f.feature_type ?? "feature").replace(/_/g, " ");
  return f.count && f.count > 1 ? `${base} ×${f.count}` : base;
}

export function componentTolerances(c: Component): DimensionRow[] {
  return (c.features ?? [])
    .filter((f) => f.tolerance_plus != null || f.tolerance_minus != null)
    .map((f) => ({
      label: prettyFeatureLabel(f),
      nominal: featureNominal(f),
      unit: "mm",
      tolerance_plus: f.tolerance_plus ?? null,
      tolerance_minus: f.tolerance_minus ?? null,
    }));
}

export function componentGdt(c: Component): GdtCallout[] {
  const out: GdtCallout[] = [];
  for (const f of c.features ?? []) {
    for (const callout of f.gdt_callouts ?? []) {
      // The wire format only gives a raw callout string per feature — we can't
      // decompose into symbol / tolerance / datum refs here, so the symbol
      // column carries the callout verbatim and the rest stay blank.
      out.push({
        symbol: callout,
        feature_label: prettyFeatureLabel(f),
      });
    }
  }
  return out;
}

export function componentThreads(c: Component): ThreadSpec[] {
  return (c.features ?? [])
    .filter((f) => THREAD_RE.test(f.feature_type ?? "") || f.dimensions?.thread_pitch_mm != null)
    .map((f) => ({
      spec: prettyFeatureLabel(f),
      count: f.count,
      depth_mm: f.dimensions?.depth_mm,
    }));
}

/** Notes are drawing-level only — components don't carry their own notes. */
export function drawingNotes(vlm: VlmExtraction | null | undefined): string[] {
  return (vlm?.drawing_notes ?? [])
    .map((n) => (typeof n === "string" ? n : n?.text ?? ""))
    .filter((s) => s && s.trim().length > 0);
}

/* Drawing-level passthroughs — used when no component is selected. */

export function drawingTolerances(vlm: VlmExtraction | null | undefined): DimensionRow[] {
  return (vlm?.dimensions ?? []).filter(
    (d) => d.tolerance || d.tolerance_plus != null || d.tolerance_minus != null,
  );
}

export function drawingGdt(vlm: VlmExtraction | null | undefined): GdtCallout[] {
  return vlm?.gdt_callouts ?? [];
}

export function drawingThreads(vlm: VlmExtraction | null | undefined): ThreadSpec[] {
  return vlm?.threads ?? [];
}
