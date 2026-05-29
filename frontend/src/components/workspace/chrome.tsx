"use client";

import { Plus, X, Cpu, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Shared presentation chrome for the estimate views — the page header, the
 * scrolling body wrapper, the first-run empty state, and the inline info/error
 * card. Pure presentation; no data fetching or pipeline state lives here.
 */

/**
 * Page header. Per the 27 May review it shows the Part Number + Revision (not
 * the STEP file name) and the sub-header line is gone — any live status sits
 * inline as a small badge so it doesn't read as a second title line.
 */
export function TopBar({
  title, statusBadge, streaming, onStop, onNewEstimate,
}: {
  title: string;
  statusBadge?: { label: string; tone: "info" | "secondary" | "destructive" } | null;
  streaming?: boolean;
  onStop?: () => void;
  onNewEstimate: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-background px-4 py-3">
      <div className="flex min-w-0 items-center gap-2">
        <h2 className="truncate text-sm font-semibold text-foreground" title={title}>{title}</h2>
        {statusBadge && (
          <Badge variant={statusBadge.tone} className="shrink-0 text-[10px]">{statusBadge.label}</Badge>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {streaming && onStop && (
          <Button variant="destructive" size="sm" className="gap-1.5" onClick={onStop}>
            <X className="h-3.5 w-3.5" /> Stop
          </Button>
        )}
        <Button variant="outline" size="sm" className="gap-1.5" onClick={onNewEstimate}>
          <Plus className="h-3.5 w-3.5" /> New Project
        </Button>
      </div>
    </div>
  );
}

/** Vertically-scrolling page body; content spans the full width (capped). */
export function ScrollBody({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="mx-auto max-w-[1700px] space-y-4">{children}</div>
    </div>
  );
}

export function EmptyState({ onNewEstimate }: { onNewEstimate: () => void }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-md space-y-6 text-center">
        <div className="brand-gradient mx-auto flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg">
          <Cpu className="h-8 w-8 text-white" />
        </div>
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-3.5 py-1">
            <Sparkles className="h-3 w-3 text-primary" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-primary/80">CNC Costing AI</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Manufacturing cost estimator</h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Upload a 3D STEP model and 2D drawing. The pipeline extracts features, plans the
            machining process, and returns a per-component cost estimate you can review and correct.
          </p>
        </div>
        <Button size="lg" className="gap-2" onClick={onNewEstimate}>
          <Plus className="h-4 w-4" /> Start a new project
        </Button>
        <p className="text-xs text-muted-foreground/70">…or pick a past run from the panel on the left.</p>
      </div>
    </div>
  );
}

export function InfoCard({
  icon, title, children, tone = "default",
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
  tone?: "default" | "error" | "warn";
}) {
  return (
    <div className={cn(
      "rounded-xl border px-4 py-3.5",
      tone === "error" ? "border-red-200 bg-red-50" :
      tone === "warn" ? "border-amber-200 bg-amber-50" :
      "border-border bg-card",
    )}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm font-semibold text-foreground">{title}</span>
      </div>
      <p className="mt-1 pl-6 text-[13px] text-muted-foreground">{children}</p>
    </div>
  );
}
