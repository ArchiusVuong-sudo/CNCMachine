"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ReadablePayload } from "./readable-payload";
import {
  ChevronDown,
  Eye,
  Layers,
  Wrench,
  Timer,
  DollarSign,
  Search,
  ShieldCheck,
  Loader2,
  CheckCircle2,
  XCircle,
  CircleDot,
  GitMerge,
  Box,
  Package,
  PackageOpen,
  Hammer,
  ListChecks,
  Cog,
  Drill,
  Boxes,
} from "lucide-react";

const TOOL_META: Record<string, { icon: typeof Eye; label: string; accent: string }> = {
  // 2D + 3D extraction
  analyze_drawing:        { icon: Eye,         label: "Vision Extraction",   accent: "text-violet-400 bg-violet-500/10 border-violet-500/20" },
  recognize_features:     { icon: Layers,      label: "Feature Recognition", accent: "text-blue-400   bg-blue-500/10   border-blue-500/20"   },
  analyze_step_file:      { icon: Layers,      label: "3D Analysis",         accent: "text-sky-400    bg-sky-500/10    border-sky-500/20"    },
  analyze_step_assembly:  { icon: PackageOpen, label: "Assembly Analysis",   accent: "text-sky-500    bg-sky-500/10    border-sky-500/20"    },
  detect_welding:         { icon: Hammer,      label: "Welding Detection",   accent: "text-yellow-500 bg-yellow-500/10 border-yellow-500/20" },
  // Routing / cost
  lookup_material:        { icon: Search,      label: "Material Lookup",     accent: "text-amber-400  bg-amber-500/10  border-amber-500/20"  },
  map_bom_to_components:  { icon: GitMerge,    label: "BOM → Components",    accent: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20" },
  map_cnc_processes:      { icon: Wrench,      label: "Process Mapping",     accent: "text-orange-400 bg-orange-500/10 border-orange-500/20" },
  match_stock:            { icon: Box,         label: "Stock Matching",      accent: "text-amber-500  bg-amber-500/10  border-amber-500/20"  },
  generate_gcode:         { icon: Wrench,      label: "G-code Generation",   accent: "text-orange-500 bg-orange-500/10 border-orange-500/20" },
  estimate_cycle_time:    { icon: Timer,       label: "Cycle Time",          accent: "text-cyan-400   bg-cyan-500/10   border-cyan-500/20"   },
  estimate_cost:          { icon: DollarSign,  label: "Cost Estimation",     accent: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
  validate_estimate:      { icon: ShieldCheck, label: "Validation",          accent: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20" },
  // kb_engine — agentic mode. Each emits per-component so the activity feed
  // tags them with "Comp N" via component_index (see ToolExecutionProps).
  "kb_engine.process_agent": { icon: ListChecks, label: "Process Agent",   accent: "text-violet-500 bg-violet-500/10 border-violet-500/20" },
  "kb_engine.machine_agent": { icon: Cog,        label: "Machine Agent",   accent: "text-sky-500    bg-sky-500/10    border-sky-500/20"    },
  "kb_engine.tool_agent":    { icon: Drill,      label: "Tool Agent",      accent: "text-orange-500 bg-orange-500/10 border-orange-500/20" },
  "kb_engine.stock_agent":   { icon: Boxes,      label: "Stock Agent",     accent: "text-amber-500  bg-amber-500/10  border-amber-500/20"  },
  "kb_engine.cost_agent":    { icon: DollarSign, label: "Cost Agent",      accent: "text-emerald-500 bg-emerald-500/10 border-emerald-500/20" },
  "kb_engine.estimate_cost": { icon: DollarSign, label: "Cost Rollup",     accent: "text-emerald-500 bg-emerald-500/10 border-emerald-500/20" },
};

interface ToolExecutionProps {
  tool: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  duration?: number;
  status: "running" | "complete" | "error";
  /** 0-indexed component slot (kb_engine pipeline). Renders as "Comp N+1" badge. */
  componentIndex?: number;
}

export function ToolExecution({ tool, args, result, duration, status, componentIndex }: ToolExecutionProps) {
  const [expanded, setExpanded] = useState(false);

  // Per-component tools are dynamic names like "process_component_3" — show a
  // friendly label rather than the raw tool string.
  const perCompMatch = tool.match(/^process_component_(\d+)$/);
  const meta = TOOL_META[tool]
    ?? (perCompMatch
      ? { icon: Package, label: `Component ${perCompMatch[1]}`, accent: "text-amber-500 bg-amber-500/10 border-amber-500/20" }
      : { icon: CircleDot, label: tool, accent: "text-slate-400 bg-slate-500/10 border-slate-500/20" });
  const Icon = meta.icon;

  // kb_engine summary (op count, machine names, $, etc.) lives in
  // result.summary — see _emit_agent_pair in orchestrator.py. Render as
  // result badges next to the tool name so the user can scan the feed.
  const summary = (result?.summary as Record<string, unknown> | undefined) ?? null;
  const summaryBadges = summary ? formatKbSummary(tool, summary) : [];

  return (
    <div className={cn("rounded-lg border overflow-hidden", meta.accent)}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left hover:bg-foreground/5 transition-all"
      >
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="text-[13px] font-medium">{meta.label}</span>
        {componentIndex != null && Number.isFinite(componentIndex) && (
          <Badge
            variant="outline"
            className="text-[10px] font-mono px-1.5 py-0 h-4 border-current/30 text-current/70 bg-current/5"
            title={`Component ${componentIndex + 1}`}
          >
            Comp {componentIndex + 1}
          </Badge>
        )}
        <span className="flex-1" />

        {summaryBadges.length > 0 && <ResultBadges items={summaryBadges} />}

        {status === "running" && <Loader2 className="w-3.5 h-3.5 animate-spin opacity-60" />}
        {status === "complete" && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
        {status === "error" && <XCircle className="w-3.5 h-3.5 text-red-400" />}

        {duration !== undefined && (
          <Badge variant="outline" className="text-[10px] font-mono border-current/20 text-current/60">
            {duration < 1000 ? `${duration}ms` : `${(duration / 1000).toFixed(1)}s`}
          </Badge>
        )}

        {result && tool === "analyze_drawing" && (
          <ResultBadges
            items={[
              (result.feature_count as number) != null && `${result.feature_count} features`,
              (result.dimension_count as number) != null && `${result.dimension_count} dims`,
              (result.gdt_count as number) != null && `${result.gdt_count} GD&T`,
              (result.bom_items as number) != null && `${result.bom_items} BOM`,
            ].filter(Boolean) as string[]}
          />
        )}
        {result && tool === "analyze_step_file" && (result.part_type as string) && (
          <Badge variant="secondary" className="text-[10px] font-mono">
            {result.part_type as string}
          </Badge>
        )}
        {result && tool === "analyze_step_assembly" && (
          <ResultBadges
            items={[
              (result.component_count as number) != null && `${result.component_count} comp`,
              (result.total_volume_mm3 as number) > 0 && `${((result.total_volume_mm3 as number) / 1000).toFixed(1)} cm³`,
            ].filter(Boolean) as string[]}
          />
        )}
        {result && tool === "recognize_features" && (
          <Badge variant="secondary" className="text-[10px]">
            {(result.feature_count as number) || 0} classified
          </Badge>
        )}
        {result && tool === "map_bom_to_components" && (
          <ResultBadges
            items={[
              (result.mapped_count as number) != null && (result.total_components as number) != null
                ? `${result.mapped_count}/${result.total_components} matched`
                : null,
              (result.unmatched_bom as number) > 0 && `${result.unmatched_bom} unmatched`,
            ].filter(Boolean) as string[]}
          />
        )}
        {result && tool === "map_cnc_processes" && (
          <Badge variant="secondary" className="text-[10px]">
            {(result.operation_count as number) || 0} ops
          </Badge>
        )}
        {result && tool === "estimate_cycle_time" && (
          <Badge variant="secondary" className="text-[10px] font-mono">
            {(result.total_minutes as number)?.toFixed(1)} min
          </Badge>
        )}
        {result && tool === "estimate_cost" && (
          <Badge variant="secondary" className="text-[10px] font-mono">
            ${(result.total_usd as number)?.toFixed(2)}
          </Badge>
        )}
        {result && perCompMatch && (
          <ResultBadges
            items={[
              (result.part_type as string) || null,
              (result.cycle_time_min as number) != null && `${(result.cycle_time_min as number).toFixed(1)} min`,
              (result.cost_usd as number) != null && `$${(result.cost_usd as number).toFixed(2)}`,
            ].filter(Boolean) as string[]}
          />
        )}

        <ChevronDown className={cn("w-3.5 h-3.5 opacity-40 transition-transform", expanded && "rotate-180")} />
      </button>

      {expanded && (
        <div className="border-t border-current/15 px-3 py-2.5 space-y-2 bg-background/40">
          {args && (
            <div>
              <div className="text-[10px] font-semibold text-current/60 uppercase tracking-wider mb-1.5">Input</div>
              <ReadablePayload payload={args} />
            </div>
          )}
          {result && (
            <div>
              <div className="text-[10px] font-semibold text-current/60 uppercase tracking-wider mb-1.5">Output</div>
              <ReadablePayload payload={result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultBadges({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {items.map((label, i) => (
        <Badge key={i} variant="secondary" className="text-[10px] font-mono">
          {label}
        </Badge>
      ))}
    </div>
  );
}

/** Render kb_engine per-agent decision summaries as 1-2 result badges so the
 *  activity feed shows what each agent actually decided without expanding the
 *  row. Keep it tight — long machine names get truncated.
 */
function formatKbSummary(tool: string, summary: Record<string, unknown>): string[] {
  const trunc = (s: unknown, n = 18): string => {
    const t = String(s ?? "").trim();
    return t.length > n ? t.slice(0, n - 1) + "…" : t;
  };

  if (tool === "kb_engine.process_agent") {
    const n = Number(summary.op_count);
    return Number.isFinite(n) && n > 0 ? [`${n} ops`] : [];
  }
  if (tool === "kb_engine.machine_agent") {
    const names = (summary.machine_names as string[] | undefined) ?? [];
    if (names.length === 1) return [trunc(names[0])];
    if (names.length > 1)   return [`${names.length} machines`, trunc(names[0])];
    const n = Number(summary.machine_count);
    return Number.isFinite(n) && n > 0 ? [`${n} machines`] : [];
  }
  if (tool === "kb_engine.tool_agent") {
    const names = (summary.tool_names as string[] | undefined) ?? [];
    const n = Number(summary.tool_count);
    if (names.length === 1) return [trunc(names[0])];
    if (Number.isFinite(n) && n > 0) return [`${n} tools`];
    return [];
  }
  if (tool === "kb_engine.stock_agent") {
    const name = trunc(summary.stock_name);
    const form = trunc(summary.stock_form, 10);
    const parts: string[] = [];
    if (name) parts.push(name);
    if (form) parts.push(form);
    return parts;
  }
  if (tool === "kb_engine.cost_agent") {
    const usd = Number(summary.total_cost_usd);
    const min = Number(summary.total_cycle_min);
    const parts: string[] = [];
    if (Number.isFinite(usd) && usd > 0) parts.push(`$${usd.toFixed(2)}`);
    if (Number.isFinite(min) && min > 0) parts.push(`${min.toFixed(1)} min`);
    return parts;
  }
  return [];
}
