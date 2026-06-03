"use client";

import { useMemo } from "react";
import { Cog, Gauge, Cpu } from "lucide-react";
import type { Component, RoutingRow, RankedMachine } from "@/lib/api/types";
import { deriveComplexity } from "@/lib/domain/complexity";
import { cn } from "@/lib/utils";

/**
 * Manufacturing Plan + Complexity card.
 *
 * Surfaces planner data that the pipeline already produces and ships in the
 * final_answer but the UI never rendered:
 *   - machine class + ranked top-3 machines (score / burden / reason)
 *   - the agent's rationale
 *   - the operation sequence (op code, tool, run minutes)
 *   - per-tool feeds & speeds (spindle / feed / stepdown / stepover), read from
 *     `raw_manufacturing_processes` which results-adapter preserves before the
 *     costed routing rows overwrite `manufacturing_processes`.
 *   - a derived complexity summary (feature / tight-tolerance / thread / GD&T
 *     counts + a Low/Medium/High band) computed from the component's features.
 */

function num(v: unknown): number | null {
  return typeof v === "number" && isFinite(v) ? v : null;
}
function fmt(v: unknown, digits = 0): string {
  const n = num(v);
  if (n == null) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(digits);
}

/** Pick the component whose plan to show: the selected one, else the richest
 *  planner-bearing component (typically the assembly owner with all the ops). */
function pickTarget(components: Component[], selectedIndex: number | null): Component | null {
  if (selectedIndex != null) {
    const sel = components.find((c) => c.component_index === selectedIndex);
    if (sel) return sel;
  }
  const withPlan = components.filter((c) => (c.planner ?? c.agentic) || (c.manufacturing_processes ?? []).length);
  if (!withPlan.length) return components[0] ?? null;
  return withPlan.reduce((best, c) =>
    (c.manufacturing_processes ?? []).length > (best.manufacturing_processes ?? []).length ? c : best,
  withPlan[0]);
}

export function ManufacturingPlanCard({
  components, selectedIndex, className,
}: {
  components: Component[];
  selectedIndex: number | null;
  className?: string;
}) {
  const target = useMemo(() => pickTarget(components, selectedIndex), [components, selectedIndex]);
  if (!target) return null;

  const planner = target.planner ?? target.agentic ?? {};
  const ranked: RankedMachine[] = planner.ranked_machines ?? planner.top_machines ?? [];
  const ops: RoutingRow[] = target.manufacturing_processes ?? [];
  const rawProcs: RoutingRow[] = (target.raw_manufacturing_processes ?? []) as RoutingRow[];
  const feeds = rawProcs.filter((p) => num(p.spindle_rpm) != null || num(p.feed_mm_per_min) != null
    || num((p as Record<string, unknown>).spindle_speed_rpm) != null || num((p as Record<string, unknown>).feed_rate_mm_min) != null);
  const complexity = useMemo(() => deriveComplexity(target), [target]);
  const rationale = typeof planner.rationale === "string" ? planner.rationale : null;

  const machineClassLabel = (planner.machine_class ?? "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const scope = target.name ?? `Component ${target.component_index}`;

  const bandTone = complexity.band === "High" ? "bg-red-100 text-red-700"
    : complexity.band === "Medium" ? "bg-amber-100 text-amber-700"
    : "bg-emerald-100 text-emerald-700";

  return (
    <div className={cn("rounded-xl border border-border bg-card", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Cog className="h-4 w-4" />
        </div>
        <h3 className="text-sm font-semibold leading-none">Manufacturing Plan</h3>
        <span className="truncate text-[11px] text-muted-foreground">· {scope}</span>
        <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", bandTone)}>
          {complexity.band} complexity
        </span>
      </div>

      {/* Complexity summary strip */}
      <div className="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-4">
        <Stat label="Features" value={complexity.nFeatures} />
        <Stat label="Tight tol." value={complexity.nTight} />
        <Stat label="Threads" value={complexity.nThreads} />
        <Stat label="GD&T" value={complexity.nGdt} />
      </div>

      <div className="space-y-4 p-4">
        {/* Machine selection */}
        <Section icon={<Cpu className="h-3.5 w-3.5" />} title="Machine selection"
          right={machineClassLabel ? <Badge>{machineClassLabel}</Badge> : null}>
          {ranked.length === 0 ? (
            <p className="text-sm text-muted-foreground">No machine ranking recorded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-[13px]">
                <thead><tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <Th>#</Th><Th>Machine</Th><Th className="text-right">Score</Th><Th className="text-right">$/hr</Th><Th>Why</Th>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {ranked.slice(0, 3).map((m, i) => (
                    <tr key={i} className={cn(i === 0 && "bg-primary/5")}>
                      <Td>{m.rank ?? i + 1}</Td>
                      <Td className="font-medium">{m.machine_name ?? m.machine_id ?? "—"}</Td>
                      <Td className="text-right tabular-nums">{fmt(m.score, 2)}</Td>
                      <Td className="text-right tabular-nums">{fmt((m as Record<string, unknown>).burden_rate_usd_per_hr ?? m.hourly_rate_usd, 0)}</Td>
                      <Td className="text-muted-foreground">{typeof (m as Record<string, unknown>).reason === "string" ? (m as Record<string, unknown>).reason as string : "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>

        {/* Operation sequence */}
        {ops.length > 0 && (
          <Section icon={<Cog className="h-3.5 w-3.5" />} title={`Operation sequence (${ops.length})`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[480px] text-[13px]">
                <thead><tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <Th>Seq</Th><Th>Operation</Th><Th>Tool</Th><Th className="text-right">Ø mm</Th><Th className="text-right">Run min</Th>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {ops.map((p, i) => (
                    <tr key={i}>
                      <Td className="tabular-nums">{p.sequence ?? i + 1}</Td>
                      <Td className="font-mono text-xs">{p.op_code ?? p.process_type ?? "—"}</Td>
                      <Td className="text-muted-foreground">{p.tool_type ?? "—"}</Td>
                      <Td className="text-right tabular-nums">{fmt(p.tool_dimensions?.diameter_mm, 1)}</Td>
                      <Td className="text-right tabular-nums">{fmt(p.run_min_per_part ?? p.cycle_time_min, 1)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {/* Feeds & speeds (novel parts only — exact-match adoptions carry none) */}
        {feeds.length > 0 && (
          <Section icon={<Gauge className="h-3.5 w-3.5" />} title="Feeds & speeds">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-[13px]">
                <thead><tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                  <Th>Operation</Th><Th>Tool</Th><Th className="text-right">Spindle RPM</Th><Th className="text-right">Feed mm/min</Th><Th className="text-right">Stepdown</Th><Th className="text-right">Stepover</Th>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {feeds.map((p, i) => {
                    const pr = p as Record<string, unknown>;
                    return (
                      <tr key={i}>
                        <Td className="font-mono text-xs">{p.op_code ?? p.process_type ?? "—"}</Td>
                        <Td className="text-muted-foreground">{(pr.tool_name as string) ?? p.tool_type ?? "—"}</Td>
                        <Td className="text-right tabular-nums">{fmt(p.spindle_rpm ?? pr.spindle_speed_rpm, 0)}</Td>
                        <Td className="text-right tabular-nums">{fmt(p.feed_mm_per_min ?? pr.feed_rate_mm_min, 0)}</Td>
                        <Td className="text-right tabular-nums">{fmt(pr.stepdown_mm ?? p.depth_of_cut_mm, 2)}</Td>
                        <Td className="text-right tabular-nums">{fmt(pr.stepover_mm, 2)}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {/* Rationale */}
        {rationale && (
          <Section icon={<Cpu className="h-3.5 w-3.5" />} title="Planner rationale">
            <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[13px] leading-relaxed text-muted-foreground">
              {rationale}
            </p>
          </Section>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-card px-4 py-2.5">
      <div className="text-lg font-semibold tabular-nums text-foreground">{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
function Section({ icon, title, right, children }: { icon: React.ReactNode; title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground/80">
        <span className="text-muted-foreground">{icon}</span>{title}
        {right && <span className="ml-auto">{right}</span>}
      </div>
      {children}
    </div>
  );
}
function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-md bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{children}</span>;
}
function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return <th className={cn("px-3 py-1.5 text-left font-medium", className)}>{children}</th>;
}
function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn("px-3 py-1.5 align-top", className)}>{children}</td>;
}
