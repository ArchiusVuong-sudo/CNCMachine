"use client";

import { useMemo } from "react";
import {
  Boxes, Ruler, Crosshair, Spline, StickyNote,
} from "lucide-react";
import type { FinalAnswer, DimensionRow, GdtCallout, ThreadSpec, Component } from "@/lib/api/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { TitleBlock } from "./title-block";
import { cn } from "@/lib/utils";

interface ExtractionPanelProps {
  results: FinalAnswer | null;
  className?: string;
}

interface FeatureAgg {
  type: string;
  count: number;
  components: Set<number>;
  sampleDims: string[];
}

function fmtNum(n: unknown, digits = 2): string | null {
  if (typeof n !== "number" || !isFinite(n)) return null;
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

function featureDimsSummary(dims?: Record<string, number | undefined>): string {
  if (!dims) return "";
  const parts: string[] = [];
  if (fmtNum(dims.diameter_mm)) parts.push(`Ø${fmtNum(dims.diameter_mm)}`);
  if (fmtNum(dims.depth_mm)) parts.push(`↧${fmtNum(dims.depth_mm)}`);
  if (fmtNum(dims.width_mm)) parts.push(`w${fmtNum(dims.width_mm)}`);
  if (fmtNum(dims.length_mm)) parts.push(`l${fmtNum(dims.length_mm)}`);
  if (fmtNum(dims.radius_mm)) parts.push(`R${fmtNum(dims.radius_mm)}`);
  return parts.join(" ");
}

function aggregateFeatures(components: Component[]): FeatureAgg[] {
  const map = new Map<string, FeatureAgg>();
  for (const comp of components ?? []) {
    for (const feat of comp.features ?? []) {
      const type = feat.feature_type || "unknown";
      const agg = map.get(type) ?? { type, count: 0, components: new Set<number>(), sampleDims: [] };
      agg.count += typeof feat.count === "number" ? feat.count : 1;
      agg.components.add(comp.component_index);
      const dim = featureDimsSummary(feat.dimensions);
      if (dim && agg.sampleDims.length < 4 && !agg.sampleDims.includes(dim)) agg.sampleDims.push(dim);
      map.set(type, agg);
    }
  }
  return Array.from(map.values()).sort((a, b) => b.count - a.count);
}

function toleranceText(d: DimensionRow): string {
  if (d.tolerance) return d.tolerance;
  const plus = fmtNum(d.tolerance_plus, 3);
  const minus = fmtNum(d.tolerance_minus, 3);
  if (plus && minus) return `+${plus} / −${minus}`;
  if (plus) return `±${plus}`;
  return "—";
}

export function ExtractionPanel({ results, className }: ExtractionPanelProps) {
  const vlm = results?.vlm_extraction ?? null;
  const components = results?.components ?? [];

  const features = useMemo(() => aggregateFeatures(components), [components]);
  const dimensions = (vlm?.dimensions ?? []) as DimensionRow[];
  const toleranced = useMemo(
    () => dimensions.filter((d) => d.tolerance || d.tolerance_plus != null || d.tolerance_minus != null),
    [dimensions],
  );
  const gdt = (vlm?.gdt_callouts ?? []) as GdtCallout[];
  const threads = (vlm?.threads ?? []) as ThreadSpec[];
  const notes = useMemo(
    () => (vlm?.drawing_notes ?? []).map((n) => (typeof n === "string" ? n : n?.text ?? "")).filter(Boolean),
    [vlm],
  );

  return (
    <div className={cn("space-y-4", className)}>
      <TitleBlock vlm={vlm} />

      <div className="rounded-xl border border-border bg-card">
        <Tabs defaultValue="features">
          <div className="border-b border-border px-2 pt-2">
            <TabsList className="h-auto w-full justify-start gap-1 bg-transparent p-0">
              <TabTrigger value="features" icon={<Boxes className="h-3.5 w-3.5" />} label="Features" count={features.length} />
              <TabTrigger value="tolerances" icon={<Ruler className="h-3.5 w-3.5" />} label="Tolerances" count={toleranced.length} />
              <TabTrigger value="gdt" icon={<Crosshair className="h-3.5 w-3.5" />} label="GD&T" count={gdt.length} />
              <TabTrigger value="threads" icon={<Spline className="h-3.5 w-3.5" />} label="Threads" count={threads.length} />
              <TabTrigger value="notes" icon={<StickyNote className="h-3.5 w-3.5" />} label="Notes" count={notes.length} />
            </TabsList>
          </div>

          <TabsContent value="features" className="m-0 p-0">
            {features.length === 0 ? <Empty label="No features detected" /> : (
              <Grid head={["Feature", "Count", "Parts", "Sample dims"]}>
                {features.map((f) => (
                  <Row key={f.type} cells={[
                    <span key="t" className="font-medium capitalize">{f.type.replace(/_/g, " ")}</span>,
                    <span key="c" className="tabular-nums">{f.count}</span>,
                    <span key="p" className="tabular-nums text-muted-foreground">{f.components.size}</span>,
                    <span key="d" className="font-mono text-xs text-muted-foreground">{f.sampleDims.join("  ") || "—"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="tolerances" className="m-0 p-0">
            {toleranced.length === 0 ? <Empty label="No toleranced dimensions detected" /> : (
              <Grid head={["Dimension", "Nominal", "Tolerance", "Notes"]}>
                {toleranced.map((d, i) => (
                  <Row key={i} cells={[
                    <span key="l" className="font-medium">{d.label || `Dim ${i + 1}`}</span>,
                    <span key="n" className="tabular-nums">{fmtNum(d.nominal) ?? (d.nominal != null ? String(d.nominal) : "—")}{d.unit ? ` ${d.unit}` : ""}</span>,
                    <span key="t" className="font-mono text-xs">{toleranceText(d)}</span>,
                    <span key="o" className="text-xs text-muted-foreground">{d.notes || "—"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="gdt" className="m-0 p-0">
            {gdt.length === 0 ? <Empty label="No GD&T callouts detected" /> : (
              <Grid head={["Symbol", "Tolerance", "Datum refs", "Feature"]}>
                {gdt.map((g, i) => (
                  <Row key={i} cells={[
                    <span key="s" className="font-mono font-semibold">{g.symbol || "—"}</span>,
                    <span key="t" className="font-mono text-xs">{g.tolerance || "—"}</span>,
                    <span key="d" className="font-mono text-xs text-muted-foreground">{(g.datum_refs ?? []).join(", ") || "—"}</span>,
                    <span key="f" className="text-xs text-muted-foreground">{g.feature_label || "—"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="threads" className="m-0 p-0">
            {threads.length === 0 ? <Empty label="No threads detected" /> : (
              <Grid head={["Spec", "Count", "Depth", "Type"]}>
                {threads.map((t, i) => (
                  <Row key={i} cells={[
                    <span key="s" className="font-mono font-medium">{t.spec || t.label || "—"}</span>,
                    <span key="c" className="tabular-nums">{t.count ?? "—"}</span>,
                    <span key="d" className="tabular-nums">{fmtNum(t.depth_mm) ? `${fmtNum(t.depth_mm)} mm` : "—"}</span>,
                    <span key="b" className="text-xs text-muted-foreground">{t.is_blind == null ? "—" : t.is_blind ? "Blind" : "Through"}</span>,
                  ]} />
                ))}
              </Grid>
            )}
          </TabsContent>

          <TabsContent value="notes" className="m-0 p-0">
            {notes.length === 0 ? <Empty label="No drawing notes detected" /> : (
              <ol className="divide-y divide-border">
                {notes.map((n, i) => (
                  <li key={i} className="flex gap-3 px-4 py-2.5 text-sm">
                    <span className="select-none font-mono text-xs text-muted-foreground">{i + 1}.</span>
                    <span className="text-foreground/90">{n}</span>
                  </li>
                ))}
              </ol>
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
