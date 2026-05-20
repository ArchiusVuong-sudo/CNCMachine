"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Loader2, Sparkles, CheckCircle2 } from "lucide-react";
import type { CanvasComponent } from "@/lib/hooks/useApproach4";
import { ComponentInspector } from "./ComponentInspector";
import { CostContributionChart } from "./CostContributionChart";
import { ProcessDistributionChart } from "./ProcessDistributionChart";
import { PipelineFlowDiagram } from "./PipelineFlowDiagram";

interface Props {
  components: Record<number, CanvasComponent>;
  isStreaming?: boolean;
  isDone?: boolean;
  totalUsd?: number | null;
  totalMinutes?: number | null;
  compact?: boolean;
}

export function LiveCanvas({ components, isStreaming, isDone, totalUsd, totalMinutes, compact }: Props) {
  const sortedComps = useMemo(() => {
    return Object.values(components).sort((a, b) => a.index - b.index);
  }, [components]);

  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  // When components arrive, default the active tab to the first one. When a
  // component becomes the "currently running" one, auto-focus to it so the user
  // sees the live decisions as they happen.
  useEffect(() => {
    if (sortedComps.length === 0) {
      setActiveIdx(null);
      return;
    }
    setActiveIdx((cur) => {
      if (cur != null && components[cur]) return cur;
      // Prefer the currently-running component, otherwise the first one.
      const running = sortedComps.find((c) => c.isRunning);
      return (running ?? sortedComps[0]).index;
    });
  }, [sortedComps, components]);

  const activeComp = activeIdx != null ? components[activeIdx] : null;

  if (sortedComps.length === 0) {
    return (
      <Card className="border-slate-200 h-full flex items-center justify-center">
        <div className="p-8 text-center max-w-sm">
          <div className="mx-auto w-12 h-12 rounded-full bg-gradient-to-br from-amber-100 to-amber-200 flex items-center justify-center mb-3">
            <Sparkles className="w-5 h-5 text-amber-600" />
          </div>
          <div className="text-[13px] font-semibold text-slate-800 mb-1">Live Insights Canvas</div>
          <p className="text-[11.5px] text-slate-500 leading-relaxed">
            As components are detected, each one will appear here with its KB matches, agent reasoning,
            cost waterfall, and time breakdown — no need to navigate away.
          </p>
          {isStreaming && (
            <div className="mt-4 inline-flex items-center gap-1.5 text-[11px] text-amber-700">
              <Loader2 className="w-3 h-3 animate-spin" />
              Pipeline running…
            </div>
          )}
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {/* Top KPI strip */}
      <Card className="border-slate-200">
        <div className="px-3.5 py-2.5 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-amber-100 text-amber-600">
              <Sparkles className="w-3.5 h-3.5" />
            </span>
            <span className="text-[12.5px] font-semibold text-slate-800">Live Insights Canvas</span>
            {isStreaming ? (
              <Badge variant="warning" className="gap-1 text-[10px]">
                <Loader2 className="w-2.5 h-2.5 animate-spin" /> streaming
              </Badge>
            ) : isDone ? (
              <Badge variant="success" className="gap-1 text-[10px]">
                <CheckCircle2 className="w-2.5 h-2.5" /> done
              </Badge>
            ) : null}
          </div>
          <div className="flex items-center gap-4 text-[11px] font-mono tabular-nums">
            <KpiPill label="Components" value={`${sortedComps.length}`} tone="text-indigo-600" />
            <KpiPill label="Total cost" value={totalUsd != null ? `$${totalUsd.toFixed(2)}` : "—"} tone="text-amber-600" />
            <KpiPill label="Total cycle" value={totalMinutes != null ? `${totalMinutes.toFixed(1)} min` : "—"} tone="text-blue-600" />
          </div>
        </div>
      </Card>

      {/* Assembly-wide charts (always visible at top of canvas) */}
      <div className={cn("grid gap-3", compact ? "grid-cols-1" : "grid-cols-1 md:grid-cols-2")}>
        <Card className="border-slate-200">
          <div className="px-3.5 py-2 border-b border-slate-100">
            <div className="text-[12px] font-semibold text-slate-800">Cost contribution</div>
            <div className="text-[10px] text-slate-500 mt-0.5">Total cost split across components</div>
          </div>
          <div className="px-3.5 py-3">
            <CostContributionChart components={components} activeIndex={activeIdx ?? undefined} />
          </div>
        </Card>
        <Card className="border-slate-200">
          <div className="px-3.5 py-2 border-b border-slate-100">
            <div className="text-[12px] font-semibold text-slate-800">Process-type mix</div>
            <div className="text-[10px] text-slate-500 mt-0.5">Operation counts across all components</div>
          </div>
          <div className="px-3.5 py-3">
            <ProcessDistributionChart components={components} />
          </div>
        </Card>
      </div>

      {/* Component tabs */}
      <Card className="border-slate-200 overflow-hidden">
        <div className="border-b border-slate-100 px-2 py-1.5 overflow-x-auto">
          <div className="flex gap-1 min-w-fit">
            {sortedComps.map((c) => {
              const isActive = c.index === activeIdx;
              const cost  = c.totalUsd ?? c.cost?.total_usd ?? 0;
              return (
                <button
                  key={c.index}
                  onClick={() => setActiveIdx(c.index)}
                  title={c.name || `Component ${c.index}`}
                  className={cn(
                    "group inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[11px] font-medium transition-all whitespace-nowrap",
                    isActive
                      ? "bg-slate-900 text-white"
                      : "bg-slate-50 text-slate-600 hover:bg-slate-100 hover:text-slate-800",
                  )}
                >
                  <span className={cn("inline-flex items-center justify-center w-4 h-4 rounded text-[9px] font-bold",
                    isActive ? "bg-amber-400 text-slate-900" : "bg-slate-200 text-slate-600",
                  )}>
                    {c.index + 1}
                  </span>
                  <span className="truncate max-w-[140px]">{c.name || `Component ${c.index}`}</span>
                  {c.isRunning && (
                    <Loader2 className="w-2.5 h-2.5 animate-spin shrink-0" />
                  )}
                  {!c.isRunning && cost > 0 && (
                    <span className={cn(
                      "text-[10px] font-mono",
                      isActive ? "text-amber-300" : "text-slate-400",
                    )}>
                      ${cost.toFixed(2)}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="p-3.5">
          {activeComp ? (
            <ComponentInspector comp={activeComp} compact={compact} />
          ) : (
            <div className="text-[11.5px] text-slate-400 italic py-8 text-center">Select a component to inspect</div>
          )}
        </div>
      </Card>

      {/* Final visualization: full pipeline flow as a mermaid diagram */}
      <PipelineFlowDiagram
        components={components}
        totalUsd={totalUsd}
        totalMinutes={totalMinutes}
      />
    </div>
  );
}

function KpiPill({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[9.5px] uppercase tracking-wider text-slate-400 font-semibold">{label}</span>
      <span className={cn("text-[12.5px] font-bold", tone)}>{value}</span>
    </div>
  );
}
