"use client";

import { DollarSign, Clock, Boxes, Layers } from "lucide-react";
import type { FinalAnswer } from "@/lib/api/types";
import { usd, minutes } from "@/lib/format";
import { ComponentCostCard } from "./component-cost-card";
import { cn } from "@/lib/utils";

interface ResultsPanelProps {
  results: FinalAnswer | null;
  analysisId: string | null;
  className?: string;
}

export function ResultsPanel({ results, analysisId, className }: ResultsPanelProps) {
  if (!results) return null;

  const components = results.components ?? [];
  const totalUsd = typeof results.total_usd === "number" ? results.total_usd : undefined;
  const totalMin = typeof results.total_minutes === "number" ? results.total_minutes : undefined;

  return (
    <div className={cn("space-y-4", className)}>
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat icon={<DollarSign className="h-4 w-4" />} label="Total Cost" value={usd(totalUsd)} accent />
        <Stat icon={<Clock className="h-4 w-4" />} label="Total Cycle" value={minutes(totalMin)} />
        <Stat icon={<Boxes className="h-4 w-4" />} label="Components" value={String(components.length)} />
        <Stat icon={<Layers className="h-4 w-4" />} label="Batch Size" value={String(results.batch_size ?? 1)} />
      </div>

      {/* Component cards */}
      <div className="space-y-3">
        {components.map((comp, i) => (
          <ComponentCostCard
            key={comp.id ?? comp.component_index ?? i}
            analysisId={analysisId}
            component={comp}
            defaultOpen={i === 0}
          />
        ))}
        {components.length === 0 && (
          <div className="rounded-xl border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
            No components in this estimate.
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ icon, label, value, accent }: { icon: React.ReactNode; label: string; value: string; accent?: boolean }) {
  return (
    <div className={cn("rounded-xl border border-border bg-card p-3.5", accent && "card-glow")}>
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className={cn(accent ? "text-primary" : "text-muted-foreground")}>{icon}</span>
        {label}
      </div>
      <div className={cn("mt-1.5 text-xl font-bold tabular-nums", accent && "text-primary")}>{value}</div>
    </div>
  );
}
