"use client";

import { useMemo } from "react";
import { Ruler, Crosshair, Spline } from "lucide-react";
import type { Component, DimensionRow, FinalAnswer, GdtCallout, ThreadSpec } from "@/lib/api/types";
import {
  componentTolerances, componentGdt, componentThreads,
  drawingTolerances, drawingGdt, drawingThreads,
} from "@/lib/domain/extraction-model";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

interface ExtractionPanelProps {
  results: FinalAnswer | null;
  /** Costed components (already filtered to drop the synthetic TOP_ASSEMBLY). */
  components: Component[];
  /** Selected component_index, or null for the level-0 assembly view. */
  selectedIndex: number | null;
  className?: string;
}

function fmtNum(n: unknown, digits = 2): string | null {
  if (typeof n !== "number" || !isFinite(n)) return null;
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

function toleranceText(d: DimensionRow): string {
  if (d.tolerance) return d.tolerance;
  const plus = fmtNum(d.tolerance_plus, 3);
  const minus = fmtNum(d.tolerance_minus, 3);
  if (plus && minus) return `+${plus} / −${minus}`;
  if (plus) return `±${plus}`;
  return "—";
}

/**
 * Tolerances / GD&T / Threads tabs.
 *
 * Per the 28 May review:
 *  - Notes moved to the Part Information card — the tab is gone from here.
 *  - When a level-1 component is selected, the three tabs reflect ONLY that
 *    component's features (via `extraction-model.ts`); the Assembly row falls
 *    back to the drawing-level VLM extraction so nothing is hidden by default.
 */
export function ExtractionPanel({ results, components, selectedIndex, className }: ExtractionPanelProps) {
  const vlm = results?.vlm_extraction ?? null;
  const selected = useMemo(
    () => (selectedIndex == null ? null : components.find((c) => c.component_index === selectedIndex) ?? null),
    [components, selectedIndex],
  );

  // Drawing-wide unit fallback: when an individual tolerance row's unit is
  // missing OR contradicts the drawing-level unit (a common Qwen3-VL slip
  // where the model emits "in" for a millimeter drawing), prefer the
  // title-block / dimension-unit declaration. Visible note 2 on most
  // Applied Materials drawings is literally "DIMENSIONS ARE IN MILLIMETERS".
  const drawingUnit = vlm?.title_block?.dimension_unit ?? vlm?.dimension_unit ?? null;

  const tolerances: DimensionRow[] = useMemo(
    () => (selected ? componentTolerances(selected) : drawingTolerances(vlm)),
    [selected, vlm],
  );
  const gdt: GdtCallout[] = useMemo(
    () => (selected ? componentGdt(selected) : drawingGdt(vlm)),
    [selected, vlm],
  );
  const threads: ThreadSpec[] = useMemo(
    () => (selected ? componentThreads(selected) : drawingThreads(vlm)),
    [selected, vlm],
  );

  const scopeLabel = selected
    ? (selected.name ?? `Component ${selected.component_index}`)
    : "Assembly · whole drawing";

  return (
    <div className={cn("space-y-4", className)}>
      <div className="rounded-xl border border-border bg-card">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="truncate text-[11px] text-muted-foreground">
            Showing extraction for <span className="font-medium text-foreground/80">{scopeLabel}</span>
          </span>
        </div>
        <Tabs defaultValue="tolerances">
          <div className="border-b border-border px-2 pt-2">
            <TabsList className="h-auto w-full justify-start gap-1 bg-transparent p-0">
              <TabTrigger value="tolerances" icon={<Ruler className="h-3.5 w-3.5" />} label="Tolerances" count={tolerances.length} />
              <TabTrigger value="gdt" icon={<Crosshair className="h-3.5 w-3.5" />} label="GD&T" count={gdt.length} />
              <TabTrigger value="threads" icon={<Spline className="h-3.5 w-3.5" />} label="Threads" count={threads.length} />
            </TabsList>
          </div>

          <TabsContent value="tolerances" className="m-0 p-0">
            {tolerances.length === 0 ? <Empty label={selected ? "No toleranced features on this component" : "No toleranced dimensions detected"} /> : (
              <Grid head={["Dimension", "Nominal", "Tolerance", "Notes"]}>
                {tolerances.map((d, i) => {
                  // Per-row unit, falling back to drawing-level when the row's
                  // unit is missing or disagrees with the title-block unit
                  // (extraction-time hallucination).
                  const rowUnit = d.unit && drawingUnit && d.unit !== drawingUnit
                    ? drawingUnit
                    : (d.unit ?? drawingUnit ?? undefined);
                  return (
                    <Row key={i} cells={[
                      <span key="l" className="font-medium">{d.label || `Dim ${i + 1}`}</span>,
                      <span key="n" className="tabular-nums">{fmtNum(d.nominal) ?? (d.nominal != null ? String(d.nominal) : "—")}{rowUnit ? ` ${rowUnit}` : ""}</span>,
                      <span key="t" className="font-mono">{toleranceText(d)}</span>,
                      <span key="o" className="text-muted-foreground">{d.notes || "—"}</span>,
                    ]} />
                  );
                })}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="gdt" className="m-0 p-0">
            {gdt.length === 0 ? <Empty label={selected ? "No GD&T callouts on this component" : "No GD&T callouts detected"} /> : (
              <Grid head={["Symbol", "Tolerance", "Datum refs", "Feature"]}>
                {gdt.map((g, i) => (
                  <Row key={i} cells={[
                    <span key="s" className="font-mono font-semibold">{g.symbol || "—"}</span>,
                    <span key="t" className="font-mono">{g.tolerance || "—"}</span>,
                    <span key="d" className="font-mono text-muted-foreground">{(g.datum_refs ?? []).join(", ") || "—"}</span>,
                    <span key="f" className="text-muted-foreground">{g.feature_label || "—"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="threads" className="m-0 p-0">
            {threads.length === 0 ? <Empty label={selected ? "No threaded features on this component" : "No threads detected"} /> : (
              <Grid head={["Spec", "Count", "Depth", "Type"]}>
                {threads.map((t, i) => (
                  <Row key={i} cells={[
                    <span key="s" className="font-mono font-medium">{t.spec || t.label || "—"}</span>,
                    <span key="c" className="tabular-nums">{t.count ?? "—"}</span>,
                    <span key="d" className="tabular-nums">{fmtNum(t.depth_mm) ? `${fmtNum(t.depth_mm)} mm` : "—"}</span>,
                    <span key="b" className="text-muted-foreground">{t.is_blind == null ? "—" : t.is_blind ? "Blind" : "Through"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function TabTrigger({ value, icon, label, count }: { value: string; icon: React.ReactNode; label: string; count: number }) {
  return (
    <TabsTrigger
      value={value}
      className="gap-1.5 rounded-md border-b-2 border-transparent px-3 py-2 text-xs data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
    >
      {icon}
      {label}
      {count > 0 && (
        <span className="ml-0.5 rounded bg-muted px-1.5 text-[10px] font-semibold tabular-nums text-muted-foreground">{count}</span>
      )}
    </TabsTrigger>
  );
}

function Grid({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {head.map((h) => (
              <th key={h} className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  );
}

function Row({ cells }: { cells: React.ReactNode[] }) {
  return (
    <tr className="hover:bg-muted/40">
      {cells.map((c, i) => (
        <td key={i} className="px-4 py-2.5 align-top">{c}</td>
      ))}
    </tr>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="px-4 py-8 text-center text-sm text-muted-foreground">{label}</div>;
}
