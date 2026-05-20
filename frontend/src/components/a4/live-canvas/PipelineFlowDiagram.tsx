"use client";

/**
 * PipelineFlowDiagram — end-of-canvas mermaid graph of the whole CNC run.
 *
 * Renders a deterministic flowchart showing how the pipeline stages
 * connect and what each stage produced. Built client-side from the
 * same `components` Record the rest of the canvas uses; mermaid is
 * dynamically imported on mount to keep the initial bundle small.
 *
 * Each per-component sub-flow surfaces the agentic Phase A→D output
 * (machine class, op count, cycle time, cost) so the diagram doubles
 * as a "what did each stage actually produce?" review.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Workflow, Copy, Check } from "lucide-react";
import type { CanvasComponent } from "@/lib/hooks/useApproach4";

interface Props {
  components:    Record<number, CanvasComponent>;
  totalUsd?:     number | null;
  totalMinutes?: number | null;
}

// HTML-escape for use inside mermaid labels (we use htmlLabels: true).
function h(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function esc(text: string): string {
  return h(text.replace(/[`]/g, "'").replace(/\|/g, "/").replace(/\n/g, " ").trim());
}

function clip(text: string, n: number): string {
  if (!text) return "";
  return text.length <= n ? text : text.slice(0, n - 1) + "…";
}

function shortName(c: CanvasComponent): string {
  return clip(c.name || `Component ${c.index + 1}`, 22);
}

function buildMermaid(
  components: Record<number, CanvasComponent>,
  totalUsd?: number | null,
  totalMinutes?: number | null,
): string {
  const comps = Object.values(components).sort((a, b) => a.index - b.index);
  if (comps.length === 0) return "";

  const totalBomRows  = comps.filter((c) => !!c.name).length;
  const totalOps      = comps.reduce((s, c) => s + (c.processes?.length ?? 0), 0);
  const allMaterials  = Array.from(new Set(comps.map((c) => c.material).filter(Boolean) as string[]));
  const allPartTypes  = Array.from(new Set(comps.map((c) => c.partType).filter(Boolean) as string[]));
  const totalVolumeMm3 = comps.reduce((s, c) => {
    const b = c.bbox;
    return b ? s + b.length_mm * b.width_mm * b.height_mm : s;
  }, 0);

  // Aggregate cost segments across components for the rollup node
  const segTotals: Record<string, number> = {
    raw_material: 0, setup: 0, machining: 0, deburr: 0, inspection: 0,
  };
  for (const c of comps) {
    const cost = c.cost;
    if (!cost) continue;
    segTotals.raw_material += cost.raw_material_usd ?? 0;
    segTotals.setup        += cost.setup_usd ?? 0;
    segTotals.deburr       += cost.deburr_usd ?? 0;
    segTotals.inspection   += cost.inspection_usd ?? 0;
    segTotals.machining    += Object.values(cost.machining_usd_by_process ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  }
  const segLine = Object.entries(segTotals)
    .filter(([, v]) => v > 0.005)
    .map(([k, v]) => `${k.replace("_", " ")} $${v.toFixed(0)}`)
    .join(" · ");

  const lines: string[] = [];
  lines.push("%%{init: { 'theme': 'base', 'themeVariables': {");
  lines.push("  'primaryColor':       '#fff',");
  lines.push("  'primaryTextColor':   '#1e293b',");
  lines.push("  'primaryBorderColor': '#cbd5e1',");
  lines.push("  'lineColor':          '#94a3b8',");
  lines.push("  'fontFamily':         'ui-sans-serif, system-ui, sans-serif',");
  lines.push("  'fontSize':           '12px'");
  lines.push("}, 'flowchart': { 'curve': 'basis', 'useMaxWidth': true, 'htmlLabels': true, 'nodeSpacing': 42, 'rankSpacing': 52 } }}%%");
  lines.push("graph TD");

  const subLine = (text: string, color = "#64748b") =>
    `<br/><span style='font-size:10px;color:${color}'>${text}</span>`;
  const minorLine = (text: string, color = "#475569") =>
    `<br/><span style='font-size:9.5px;color:${color}'>${text}</span>`;

  // ── Inputs ────────────────────────────────────────────────────────────
  lines.push(`  pdf["📄 2D Drawing${subLine("PDF upload")}"]:::input`);
  lines.push(`  step["🧊 3D STEP File${subLine(`${comps.length} component${comps.length === 1 ? "" : "s"}`)}"]:::input`);

  // ── Stage 1: extraction ───────────────────────────────────────────────
  const extractSummary = [
    `${totalBomRows} BOM row${totalBomRows === 1 ? "" : "s"}`,
    allMaterials.length > 0 ? `mat: ${clip(allMaterials[0], 22)}` : null,
  ].filter(Boolean).join(" · ");
  lines.push(`  extract["📐 2D Drawing Extraction${subLine("Qwen3-VL · vision + thinking")}${minorLine(esc(extractSummary), "#5b21b6")}"]:::extract`);

  const assemblySummary = [
    `${comps.length} bod${comps.length === 1 ? "y" : "ies"}`,
    totalVolumeMm3 > 0 ? `${(totalVolumeMm3 / 1000).toFixed(1)} cm³` : null,
    allPartTypes.length > 0 ? `${clip(allPartTypes[0].toLowerCase(), 18)}${allPartTypes.length > 1 ? ` +${allPartTypes.length - 1}` : ""}` : null,
  ].filter(Boolean).join(" · ");
  lines.push(`  assembly["🔍 3D Assembly Analysis${subLine("OCC feature recognition")}${minorLine(esc(assemblySummary), "#5b21b6")}"]:::extract`);

  lines.push(`  pdf --> extract`);
  lines.push(`  step --> assembly`);

  // ── Stage 2: BOM map ──────────────────────────────────────────────────
  lines.push(`  bommap{{"🔀 BOM ↔ Component Map${subLine(`${comps.length}/${totalBomRows} matched`)}"}}:::map`);
  lines.push(`  extract -- "${totalBomRows} BOM row${totalBomRows === 1 ? "" : "s"}" --> bommap`);
  lines.push(`  assembly -- "${comps.length} bod${comps.length === 1 ? "y" : "ies"}" --> bommap`);

  // ── Stage 3: per-component header + agentic summary node ──────────────
  for (const c of comps) {
    const cid    = `c${c.index}`;
    const cname  = esc(shortName(c));
    const ptype  = c.partType ? clip(c.partType.toLowerCase(), 18) : "?";
    const cost   = c.totalUsd ?? c.cost?.total_usd ?? 0;
    const cycle  = c.cycleTimeMin ?? null;
    const opCnt  = c.processes?.length ?? 0;
    const mat    = c.material ? clip(c.material, 18) : null;
    const bbox   = c.bbox
      ? `${c.bbox.length_mm.toFixed(0)}×${c.bbox.width_mm.toFixed(0)}×${c.bbox.height_mm.toFixed(0)} mm`
      : null;

    const headerL1 = [
      ptype,
      cost > 0 ? `$${cost.toFixed(2)}` : null,
      cycle != null ? `${cycle.toFixed(1)} min` : null,
      opCnt > 0 ? `${opCnt} op${opCnt === 1 ? "" : "s"}` : null,
    ].filter(Boolean).join(" · ");
    const headerL2 = [mat, bbox].filter(Boolean).join(" · ");

    let header = `<b>${cname}</b>${subLine(esc(headerL1))}`;
    if (headerL2) header += minorLine(esc(headerL2));
    lines.push(`  ${cid}_header[/"${header}"/]:::comp`);

    // Agentic plan summary (Phase A→D output condensed into one node)
    const ag = c.agentic;
    const machineClass = ag?.machine_class ? clip(ag.machine_class, 22) : "—";
    const machineId    = ag?.chosen_machine_id ? clip(ag.chosen_machine_id, 22) : "—";
    const runMin       = ag?.total_run_min_per_part != null ? `${ag.total_run_min_per_part.toFixed(1)} min` : "—";
    const setupMin     = ag?.setup_min_per_lot != null ? `${ag.setup_min_per_lot.toFixed(1)} setup` : "—";
    const analogues    = ag?.analogues_used ?? [];

    const aLine1 = `class: ${machineClass} · machine: ${machineId}`;
    const aLine2 = `run ${runMin}/part · ${setupMin}/lot${analogues.length ? ` · ${analogues.length} analogue${analogues.length === 1 ? "" : "s"}` : ""}`;

    const planLabel = `Agentic Plan${subLine(esc(aLine1))}${minorLine(esc(aLine2), "#475569")}`;
    lines.push(`  ${cid}_plan["${planLabel}"]:::agent`);

    // Cost rollup node per component
    const costLabel = `Cost ${cost > 0 ? `$${cost.toFixed(2)}` : "—"}${subLine(`${opCnt} routed op${opCnt === 1 ? "" : "s"}`)}`;
    lines.push(`  ${cid}_cost["${costLabel}"]:::agent`);

    lines.push(`  bommap --> ${cid}_header`);
    lines.push(`  ${cid}_header --> ${cid}_plan`);
    lines.push(`  ${cid}_plan --> ${cid}_cost`);
  }

  // ── Stage 4: cost rollup ──────────────────────────────────────────────
  const totalLabel = [
    totalUsd != null ? `$${totalUsd.toFixed(2)}` : null,
    totalMinutes != null ? `${totalMinutes.toFixed(1)} min` : null,
    totalOps > 0 ? `${totalOps} op${totalOps === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(" · ");
  let totalNode = `💰 Assembly Total${subLine(`<span style='color:#047857;font-weight:600'>${esc(totalLabel)}</span>`)}`;
  if (segLine) totalNode += minorLine(esc(segLine), "#047857");
  lines.push(`  total(["${totalNode}"]):::total`);
  for (const c of comps) {
    const cost  = c.totalUsd ?? c.cost?.total_usd ?? 0;
    const label = cost > 0 ? `$${cost.toFixed(2)}` : "—";
    lines.push(`  c${c.index}_cost -- "${label}" --> total`);
  }

  // ── Styles ────────────────────────────────────────────────────────────
  lines.push("  classDef input    fill:#f8fafc,stroke:#cbd5e1,stroke-width:1px,color:#334155");
  lines.push("  classDef extract  fill:#ede9fe,stroke:#a78bfa,stroke-width:1.2px,color:#5b21b6");
  lines.push("  classDef map      fill:#fef3c7,stroke:#f59e0b,stroke-width:1.2px,color:#92400e");
  lines.push("  classDef comp     fill:#eff6ff,stroke:#3b82f6,stroke-width:1.4px,color:#1e3a8a");
  lines.push("  classDef agent    fill:#fff,stroke:#cbd5e1,stroke-width:1px,color:#1e293b");
  lines.push("  classDef total    fill:#d1fae5,stroke:#10b981,stroke-width:1.6px,color:#065f46");

  return lines.join("\n");
}

function buildNotes(
  components: Record<number, CanvasComponent>,
  totalUsd?: number | null,
  totalMinutes?: number | null,
): Array<{ label: string; value: string }> {
  const comps = Object.values(components);
  const totalOps = comps.reduce((s, c) => s + (c.processes?.length ?? 0), 0);
  const totalAnalogues = comps.reduce((s, c) => s + (c.agentic?.analogues_used?.length ?? 0), 0);
  const machinesUsed = new Set<string>();
  const toolsUsed    = new Set<string>();
  for (const c of comps) {
    for (const p of c.processes ?? []) {
      if (p.machine_ref?.machine_name) machinesUsed.add(p.machine_ref.machine_name);
      if (p.tooling_ref?.tool_name)    toolsUsed.add(p.tooling_ref.tool_name);
    }
  }
  const materials = Array.from(new Set(comps.map((c) => c.material).filter(Boolean) as string[]));
  const partTypes = Array.from(new Set(comps.map((c) => c.partType).filter(Boolean) as string[]));

  return [
    { label: "Components",      value: `${comps.length}` },
    { label: "Materials",       value: materials.slice(0, 2).join(", ") || "—" },
    { label: "Part types",      value: partTypes.map((p) => p.toLowerCase()).join(", ") || "—" },
    { label: "Total ops",       value: `${totalOps}` },
    { label: "Unique machines", value: `${machinesUsed.size}` },
    { label: "Unique tools",    value: `${toolsUsed.size}` },
    { label: "KB analogues",    value: `${totalAnalogues}` },
    { label: "Cycle time",      value: totalMinutes != null ? `${totalMinutes.toFixed(1)} min` : "—" },
    { label: "Total cost",      value: totalUsd != null ? `$${totalUsd.toFixed(2)}` : "—" },
  ];
}

export function PipelineFlowDiagram({ components, totalUsd, totalMinutes }: Props) {
  const comps = Object.values(components);
  const source = useMemo(
    () => buildMermaid(components, totalUsd, totalMinutes),
    [components, totalUsd, totalMinutes],
  );
  const notes = useMemo(
    () => buildNotes(components, totalUsd, totalMinutes),
    [components, totalUsd, totalMinutes],
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const [renderState, setRenderState] = useState<"loading" | "ok" | "error">("loading");
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!source || !containerRef.current) return;
    setRenderState("loading");
    setErrMsg(null);

    (async () => {
      try {
        const mod = await import("mermaid");
        const mermaid = mod.default;
        mermaid.initialize({ startOnLoad: false, securityLevel: "loose", theme: "base" });
        const id = `cnc-pipeline-${Math.random().toString(36).slice(2, 10)}`;
        const { svg } = await mermaid.render(id, source);
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        const svgEl = containerRef.current.querySelector("svg");
        if (svgEl) {
          svgEl.removeAttribute("height");
          svgEl.style.maxWidth = "100%";
          svgEl.style.height   = "auto";
        }
        setRenderState("ok");
      } catch (e: unknown) {
        if (cancelled) return;
        setRenderState("error");
        setErrMsg(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => { cancelled = true; };
  }, [source]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore — clipboard may be blocked */ }
  };

  if (comps.length === 0) return null;

  return (
    <Card className="border-slate-200">
      <div className="px-3.5 py-2 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-md bg-sky-100 text-sky-600">
            <Workflow className="w-3.5 h-3.5" />
          </span>
          <div>
            <div className="text-[12.5px] font-semibold text-slate-800">Pipeline Flow</div>
            <div className="text-[10px] text-slate-500">How data flowed through every stage — counts and decisions on each node</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-[10px] font-mono">
            {comps.length} component{comps.length === 1 ? "" : "s"}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-[10.5px] gap-1"
            onClick={handleCopy}
            title="Copy mermaid source"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
            {copied ? "Copied" : "Copy mermaid"}
          </Button>
        </div>
      </div>

      <div className="px-3.5 py-3">
        {renderState === "loading" && (
          <div className="text-[11px] text-slate-400 italic py-6 text-center">
            Rendering pipeline diagram…
          </div>
        )}
        {renderState === "error" && (
          <div className="text-[11px] text-rose-600 py-3">
            Could not render diagram: {errMsg}
          </div>
        )}
        <div
          ref={containerRef}
          className="overflow-x-auto"
          style={{ minHeight: renderState === "loading" ? 0 : 120 }}
        />
      </div>

      {/* At-a-glance notes — same data the diagram visualizes, in plain language */}
      <div className="border-t border-slate-100 px-3.5 py-3">
        <div className="text-[10.5px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
          Run at a glance
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {notes.map((n) => (
            <div
              key={n.label}
              className="rounded-md border border-slate-200 bg-slate-50/60 px-2.5 py-1.5"
            >
              <div className="text-[9.5px] uppercase font-semibold tracking-wider text-slate-400">
                {n.label}
              </div>
              <div className="text-[11.5px] font-mono tabular-nums text-slate-800 truncate" title={n.value}>
                {n.value}
              </div>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
