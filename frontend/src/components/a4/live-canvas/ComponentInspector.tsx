"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Box, Clock, DollarSign, Cpu, Wrench, Package, Loader2 } from "lucide-react";
import type { CanvasComponent } from "@/lib/hooks/useApproach4";
import type { RoutingRow } from "@/lib/api/types";
import { CostWaterfallChart } from "./CostWaterfallChart";
import { TimeBreakdownChart } from "./TimeBreakdownChart";

interface Props {
  comp:    CanvasComponent;
  compact?: boolean;
}

function fmtBbox(bbox?: { length_mm: number; width_mm: number; height_mm: number }): string {
  if (!bbox) return "—";
  return `${bbox.length_mm.toFixed(1)} × ${bbox.width_mm.toFixed(1)} × ${bbox.height_mm.toFixed(1)} mm`;
}

export function ComponentInspector({ comp, compact }: Props) {
  const processes   = comp.processes ?? [];
  const procCount   = processes.length;
  const totalCost   = comp.totalUsd ?? comp.cost?.total_usd ?? 0;
  const cycleMin    = comp.cycleTimeMin ?? null;
  const uniqueTools = new Set(processes.map((p) => p.tooling_ref?.tool_name).filter(Boolean)).size;

  // Pick a primary machine by op count
  const machineCounts = new Map<string, number>();
  for (const p of processes) {
    const m = p.machine_ref?.machine_name;
    if (m) machineCounts.set(m, (machineCounts.get(m) || 0) + 1);
  }
  const primaryMachine = [...machineCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];

  return (
    <div className="space-y-3">
      {/* Header strip */}
      <Card className="border-slate-200">
        <div className="px-3.5 py-2.5 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h3
                className="text-[13.5px] font-semibold text-slate-900 truncate"
                title={comp.name || `Component ${comp.index}`}
              >
                {comp.name || `Component ${comp.index}`}
              </h3>
              {comp.partType && (
                <Badge variant="outline" className="text-[10px] font-mono uppercase tracking-wider">
                  {comp.partType}
                </Badge>
              )}
              {comp.isRunning && (
                <Badge variant="warning" className="text-[10px] gap-1">
                  <Loader2 className="w-2.5 h-2.5 animate-spin" /> running
                </Badge>
              )}
            </div>
            <div className="mt-0.5 text-[11px] text-slate-500 flex flex-wrap gap-x-3 gap-y-0.5">
              {comp.material && <span><span className="text-slate-400">mat:</span> {comp.material}</span>}
              <span><span className="text-slate-400">bbox:</span> {fmtBbox(comp.bbox)}</span>
            </div>
          </div>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-4 border-t border-slate-100 divide-x divide-slate-100 bg-slate-50/40">
          <Stat icon={DollarSign} label="Cost"       value={totalCost > 0 ? `$${totalCost.toFixed(2)}` : "—"} tone="text-amber-600" />
          <Stat icon={Clock}      label="Cycle"      value={cycleMin != null && cycleMin > 0 ? `${cycleMin.toFixed(1)} min` : "—"} tone="text-blue-600" />
          <Stat icon={Cpu}        label="Operations" value={procCount > 0 ? `${procCount}` : "—"} tone="text-indigo-600" />
          <Stat icon={Wrench}     label="Tools"      value={uniqueTools > 0 ? `${uniqueTools}` : "—"} tone="text-cyan-600" />
        </div>

        {primaryMachine && (
          <div className="px-3.5 py-1.5 border-t border-slate-100 text-[10.5px] text-slate-500">
            <Package className="inline w-3 h-3 mr-1 -mt-0.5 text-slate-400" />
            Primary machine: <span className="text-slate-700 font-medium">{primaryMachine}</span>
          </div>
        )}
      </Card>

      {/* Agentic-plan summary (Phase A/B/C/D output, from the new backend) */}
      {comp.agentic && <AgenticSummary agentic={comp.agentic} />}

      {/* Two-column charts */}
      <div className={cn("grid gap-3", compact ? "grid-cols-1" : "grid-cols-1 xl:grid-cols-2")}>
        <SectionCard title="Cost Waterfall" subtitle="Cost contribution by segment">
          <CostWaterfallChart cost={comp.cost ?? null} />
        </SectionCard>

        <SectionCard title="Time Breakdown" subtitle="Cycle minutes by process type">
          <TimeBreakdownChart processes={processes} />
        </SectionCard>
      </div>

      {/* Decision provenance — what's grounded vs what's an agent estimate */}
      {procCount > 0 && <DecisionProvenanceCard processes={processes} />}

      {/* Process routing table */}
      {procCount > 0 && (
        <SectionCard title="Routing Plan" subtitle={`${procCount} ordered operation${procCount === 1 ? "" : "s"}`}>
          <ProcessRoutingTable processes={processes} />
        </SectionCard>
      )}
    </div>
  );
}

/** Phase A/B/C/D output strip — replaces the old per-agent timeline. */
function AgenticSummary({ agentic }: { agentic: NonNullable<CanvasComponent["agentic"]> }) {
  const machineClass = agentic.machine_class;
  const chosen       = agentic.chosen_machine_id;
  const ranked       = agentic.ranked_machines ?? agentic.top_machines ?? [];
  const setupMin     = agentic.setup_min_per_lot;
  const runMin       = agentic.total_run_min_per_part;
  const analogues    = agentic.analogues_used ?? [];

  return (
    <SectionCard title="Agentic Plan" subtitle="Phase A → B → C → D output">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[11.5px]">
        <div className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-500">Machine class</div>
          <div className="text-[12.5px] font-semibold text-slate-800 mt-0.5">{machineClass || "—"}</div>
          {chosen && (
            <div className="text-[10px] font-mono text-slate-500 mt-1 truncate" title={chosen}>{chosen}</div>
          )}
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-500">Cycle</div>
          <div className="text-[12.5px] font-semibold text-slate-800 mt-0.5">
            {runMin != null ? `${runMin.toFixed(2)} min/part` : "—"}
          </div>
          <div className="text-[10px] text-slate-500 mt-1">
            {setupMin != null ? `+ ${setupMin.toFixed(1)} min setup/lot` : ""}
          </div>
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-500">KB analogues</div>
          <div className="text-[12.5px] font-semibold text-slate-800 mt-0.5">
            {analogues.length > 0 ? `${analogues.length} part${analogues.length === 1 ? "" : "s"}` : "—"}
          </div>
          {analogues.length > 0 && (
            <div className="text-[10px] font-mono text-slate-500 mt-1 truncate" title={analogues.join(", ")}>
              {analogues.slice(0, 3).join(", ")}{analogues.length > 3 ? "…" : ""}
            </div>
          )}
        </div>
      </div>

      {ranked.length > 0 && (
        <div className="mt-3 overflow-x-auto -mx-3.5 -my-3 px-3.5 py-3">
          <table className="text-[11px] min-w-full">
            <thead>
              <tr className="text-left text-slate-400 uppercase tracking-wider text-[9.5px] border-b border-slate-200">
                <th className="px-1.5 py-1 whitespace-nowrap">Rank</th>
                <th className="px-1.5 py-1 whitespace-nowrap">Machine</th>
                <th className="px-1.5 py-1 whitespace-nowrap">Type</th>
                <th className="px-1.5 py-1 whitespace-nowrap text-right">Rate</th>
                <th className="px-1.5 py-1 whitespace-nowrap text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {ranked.slice(0, 5).map((m, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  <td className="px-1.5 py-1 font-mono text-slate-500">#{m.rank ?? i + 1}</td>
                  <td className="px-1.5 py-1 text-slate-700">{m.machine_name || m.machine_id || "—"}</td>
                  <td className="px-1.5 py-1 text-slate-500">{m.machine_type || "—"}</td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-600">
                    {m.hourly_rate_usd != null ? `$${m.hourly_rate_usd.toFixed(0)}/h` : "—"}
                  </td>
                  <td className="px-1.5 py-1 text-right font-mono text-slate-700 font-medium">
                    {m.score != null ? m.score.toFixed(2) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

/** Per-row trust marker — green when both machine + tool resolved to catalog. */
function DecisionProvenanceCard({ processes }: { processes: RoutingRow[] }) {
  const total = processes.length;
  if (total === 0) return null;

  let grounded   = 0;
  let partial    = 0;
  let unverified = 0;
  for (const p of processes) {
    const hasM = !!p.machine_ref?.machine_id;
    const hasT = !!p.tooling_ref?.tool_id;
    if (hasM && hasT)       grounded++;
    else if (hasM || hasT)  partial++;
    else                    unverified++;
  }
  const groundedPct = Math.round((grounded / total) * 100);

  const verdict =
    groundedPct >= 75 ? { label: "Mostly grounded",   cls: "bg-emerald-50 border-emerald-200 text-emerald-800" } :
    groundedPct >= 40 ? { label: "Partially grounded", cls: "bg-amber-50 border-amber-200 text-amber-800"      } :
                        { label: "Mostly estimated",   cls: "bg-rose-50 border-rose-200 text-rose-800"          };

  return (
    <SectionCard
      title="Decision Provenance"
      subtitle="Where each routing row's numbers came from — catalog vs agent estimate"
    >
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-[11.5px]">
        <div className={`rounded-md border px-3 py-2 ${verdict.cls}`}>
          <div className="text-[9.5px] font-semibold uppercase tracking-wider opacity-70">Verdict</div>
          <div className="text-[13px] font-semibold mt-0.5">{verdict.label}</div>
          <div className="text-[10.5px] mt-0.5 opacity-80 font-mono">{groundedPct}% catalog-linked</div>
        </div>

        <div className="rounded-md border border-emerald-200 bg-emerald-50/60 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-emerald-700/70">From your cost-DB</div>
          <div className="text-[13px] font-semibold text-emerald-800 mt-0.5">{grounded} of {total}</div>
          <div className="text-[10.5px] mt-0.5 text-emerald-700/80">machine + tool both resolved</div>
        </div>

        <div className="rounded-md border border-amber-200 bg-amber-50/60 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-amber-700/70">Partial</div>
          <div className="text-[13px] font-semibold text-amber-800 mt-0.5">{partial}</div>
          <div className="text-[10.5px] mt-0.5 text-amber-700/80">one side fell back to defaults</div>
        </div>

        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
          <div className="text-[9.5px] font-semibold uppercase tracking-wider text-slate-500">Unverified</div>
          <div className="text-[13px] font-semibold text-slate-800 mt-0.5">{unverified}</div>
          <div className="text-[10.5px] mt-0.5 text-slate-600">no catalog match — treat as estimate</div>
        </div>
      </div>
    </SectionCard>
  );
}

function Stat({ icon: Icon, label, value, tone }: { icon: typeof Box; label: string; value: string; tone: string }) {
  return (
    <div className="px-3 py-2">
      <div className="flex items-center gap-1.5 text-[9.5px] uppercase font-semibold tracking-wider text-slate-400">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className={cn("text-[14px] font-bold font-mono tabular-nums mt-0.5", tone)}>{value}</div>
    </div>
  );
}

function SectionCard({
  title, subtitle, children,
}: {
  title: string; subtitle?: string; children: React.ReactNode;
}) {
  return (
    <Card className="border-slate-200">
      <div className="px-3.5 py-2 border-b border-slate-100">
        <div className="text-[12px] font-semibold text-slate-800">{title}</div>
        {subtitle && <div className="text-[10px] text-slate-500 mt-0.5">{subtitle}</div>}
      </div>
      <div className="px-3.5 py-3">
        {children}
      </div>
    </Card>
  );
}

function ProcessRoutingTable({ processes }: { processes: RoutingRow[] }) {
  if (!processes.length) return null;
  return (
    <div className="overflow-x-auto -mx-3.5 -my-3 px-3.5 py-3">
      <table className="text-[11px] min-w-full">
        <thead>
          <tr className="text-left text-slate-400 uppercase tracking-wider text-[9.5px] border-b border-slate-200">
            <th className="px-1.5 py-1.5 whitespace-nowrap">#</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap" title="Where this row's machine + tool came from">Src</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap">Process</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap">Machine</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap">Tool</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap text-right">Cycle</th>
            <th className="px-1.5 py-1.5 whitespace-nowrap text-right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {processes.map((p, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0 hover:bg-slate-50/60">
              <td className="px-1.5 py-1.5 font-mono text-slate-400 whitespace-nowrap">{p.sequence_order ?? i + 1}</td>
              <td className="px-1.5 py-1.5 whitespace-nowrap"><GroundingDot p={p} /></td>
              <td className="px-1.5 py-1.5 text-slate-700 font-medium whitespace-nowrap">{p.process_type ?? "—"}</td>
              <td className="px-1.5 py-1.5 text-slate-600 whitespace-nowrap">{p.machine_ref?.machine_name || "—"}</td>
              <td className="px-1.5 py-1.5 text-slate-600 whitespace-nowrap">{p.tooling_ref?.tool_name || "—"}</td>
              <td className="px-1.5 py-1.5 text-right font-mono tabular-nums text-slate-600 whitespace-nowrap">
                {p.cycle_time_min ? `${p.cycle_time_min.toFixed(1)}m` : "—"}
              </td>
              <td className="px-1.5 py-1.5 text-right font-mono tabular-nums text-slate-800 font-medium whitespace-nowrap">
                {p.total_cost_usd ? `$${p.total_cost_usd.toFixed(2)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroundingDot({ p }: { p: RoutingRow }) {
  const hasMachine = !!p.machine_ref?.machine_id;
  const hasTool    = !!p.tooling_ref?.tool_id;
  const score      = (hasMachine ? 1 : 0) + (hasTool ? 1 : 0);
  const cls =
    score === 2 ? "bg-emerald-500" :
    score === 1 ? "bg-amber-500"   :
                  "bg-slate-300";
  const tip =
    score === 2 ? "Both machine + tool resolved to your cost-DB catalog rows." :
    score === 1 ? `Only ${hasMachine ? "machine" : "tool"} resolved to your catalog — the other side uses default rates.` :
                  "Neither machine nor tool matched your catalog. Numbers use hard-coded fallback rates — treat as estimate.";
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${cls} ring-1 ring-current/10 cursor-help`}
      title={tip}
      aria-label={tip}
    />
  );
}
