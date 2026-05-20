"use client";

/**
 * A4DetailView — rendered inside analysis/[id]/page.tsx for a completed run.
 *
 * Consumes the `FinalAnswer` shape served by `GET /api/v1/analyses/{id}`
 * (full file when available, compact note as a fallback). Layout: 5 tabs —
 * Components | Features | Processes | Cost Breakdown | 2D Extraction.
 * G-code is no longer rendered here; the new server doesn't expose inline
 * gcode text.
 */

import { useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ComponentTree } from "@/components/a4/component-tree";
import { BomMappingTable } from "@/components/a4/bom-mapping-table";
import { CostBreakdown } from "@/components/a4/cost-breakdown";
import {
  ArrowLeft, Timer, DollarSign, Layers, PackageOpen,
  ChevronDown, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  FinalAnswer,
  Component,
  Feature,
  RoutingRow,
} from "@/lib/api/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------------------
// Feature type icon / badge helpers
// ---------------------------------------------------------------------------

const FEATURE_TYPE_COLORS: Record<string, string> = {
  through_hole:   "border-blue-200 bg-blue-50 text-blue-700",
  blind_hole:     "border-indigo-200 bg-indigo-50 text-indigo-700",
  pocket:         "border-amber-200 bg-amber-50 text-amber-700",
  slot:           "border-orange-200 bg-orange-50 text-orange-700",
  boss:           "border-emerald-200 bg-emerald-50 text-emerald-700",
  fillet:         "border-purple-200 bg-purple-50 text-purple-700",
  chamfer:        "border-pink-200 bg-pink-50 text-pink-700",
  thread:         "border-cyan-200 bg-cyan-50 text-cyan-700",
  face:           "border-slate-200 bg-slate-50 text-slate-700",
};

function featureColor(type: string): string {
  const match = Object.keys(FEATURE_TYPE_COLORS).find((k) => type.includes(k));
  return FEATURE_TYPE_COLORS[match ?? "face"];
}

function readProcesses(c: Component): RoutingRow[] {
  return (c.manufacturing_processes ?? c.processes ?? []) as RoutingRow[];
}

// ---------------------------------------------------------------------------
// Summary header cards
// ---------------------------------------------------------------------------

function SummaryCards({ result }: { result: FinalAnswer }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <Card className="py-4 border-amber-200/70 bg-gradient-to-br from-amber-50 to-yellow-50">
        <CardContent className="px-4 text-center">
          <Timer className="w-4 h-4 mx-auto text-amber-500 mb-1.5" />
          <div className="text-xl font-bold font-mono text-amber-700">
            {result.total_minutes != null ? result.total_minutes.toFixed(1) : "—"}
          </div>
          <div className="text-[9.5px] text-amber-500/60 font-mono font-semibold uppercase tracking-wide">min</div>
        </CardContent>
      </Card>
      <Card className="py-4 border-amber-200/70 bg-gradient-to-br from-amber-50 to-orange-50">
        <CardContent className="px-4 text-center">
          <DollarSign className="w-4 h-4 mx-auto text-amber-600 mb-1.5" />
          <div className="text-xl font-bold font-mono text-amber-800">
            ${result.total_usd != null ? result.total_usd.toFixed(2) : "—"}
          </div>
          <div className="text-[9.5px] text-amber-600/60 font-mono font-semibold uppercase tracking-wide">total USD</div>
        </CardContent>
      </Card>
      <Card className="py-4 border-slate-200/60 bg-white">
        <CardContent className="px-4 text-center">
          <PackageOpen className="w-4 h-4 mx-auto text-slate-500 mb-1.5" />
          <div className="text-xl font-bold font-mono text-slate-800">
            {result.components?.length ?? 0}
          </div>
          <div className="text-[9.5px] text-slate-400 font-mono font-semibold uppercase tracking-wide">components</div>
        </CardContent>
      </Card>
      <Card className="py-4 border-slate-200/60 bg-white">
        <CardContent className="px-4 text-center">
          <Layers className="w-4 h-4 mx-auto text-slate-500 mb-1.5" />
          <div className="text-xl font-bold font-mono text-slate-800">
            {result.batch_size ?? 1}
          </div>
          <div className="text-[9.5px] text-slate-400 font-mono font-semibold uppercase tracking-wide">batch qty</div>
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Features tab — grouped by component, accordion
// ---------------------------------------------------------------------------

function FeaturesTab({ components }: { components: Component[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});

  if (!components?.length) return <EmptyNote text="No components with features" />;

  return (
    <div className="space-y-2">
      {components.map((comp) => {
        const isOpen  = open[comp.component_index] ?? true;
        const featCnt = comp.features?.length ?? 0;
        return (
          <div key={comp.component_index} className="rounded-xl border border-slate-200/60 overflow-hidden">
            <button
              className="w-full flex items-center gap-3 px-4 py-3 bg-slate-50/80 hover:bg-slate-50 transition-colors text-left"
              onClick={() => setOpen((p) => ({ ...p, [comp.component_index]: !isOpen }))}
            >
              <span className="w-5 h-5 rounded-md bg-amber-100 text-amber-700 text-[9px] font-mono font-bold flex items-center justify-center shrink-0">
                {comp.component_index}
              </span>
              <span className="text-[13px] font-semibold text-slate-800 flex-1 truncate">
                {comp.name || `Component ${comp.component_index}`}
              </span>
              <Badge variant="secondary" className="text-[10px] font-mono">{featCnt} features</Badge>
              {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
            </button>

            {isOpen && (
              <div className="overflow-x-auto">
                {featCnt === 0 ? (
                  <div className="px-4 py-4 text-[12px] text-slate-400 italic">No features detected</div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-white">
                        <TableHead className="text-[10px] uppercase tracking-wider">#</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Type</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Count</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Dimensions</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">FACE IDs</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Tolerance</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">GD&T</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Source</TableHead>
                        <TableHead className="text-[10px] uppercase tracking-wider">Conf.</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(comp.features ?? []).map((f: Feature) => {
                        const callouts = ((f as any).gdt_callouts as unknown[] | undefined) ?? [];
                        const calloutStrings = callouts
                          .map((c) =>
                            typeof c === "string"
                              ? c
                              : c && typeof c === "object"
                              ? ((c as any).symbol ?? (c as any).type ?? JSON.stringify(c))
                              : String(c),
                          )
                          .filter(Boolean);
                        const source = f.source as string | undefined;
                        const faceIds = (f.face_ids ?? []) as number[];
                        const conf = f.confidence ?? 0;
                        return (
                          <TableRow key={f.feature_index}>
                            <TableCell className="font-mono text-[11px] text-slate-400">{f.feature_index}</TableCell>
                            <TableCell>
                              <Badge variant="outline" className={cn("text-[10px] font-mono", featureColor(f.feature_type ?? ""))}>
                                {(f.feature_type ?? "").replace(/_/g, " ")}
                              </Badge>
                            </TableCell>
                            <TableCell className="font-mono text-[12px]">{f.count ?? 1}</TableCell>
                            <TableCell className="text-[11.5px] text-slate-600 font-mono max-w-[180px]">
                              {formatDims(f.dimensions)}
                            </TableCell>
                            <TableCell>
                              <div className="flex flex-wrap gap-1 max-w-[120px]">
                                {faceIds.slice(0, 6).map((fid) => (
                                  <span key={fid} className="text-[9px] font-mono bg-blue-100 text-blue-700 rounded px-1 py-0.5">
                                    F{fid}
                                  </span>
                                ))}
                                {faceIds.length > 6 && (
                                  <span className="text-[9px] text-slate-400">+{faceIds.length - 6}</span>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="font-mono text-[11px] text-slate-500">
                              {f.tolerance_plus != null
                                ? `+${f.tolerance_plus} / ${f.tolerance_minus ?? 0}`
                                : "—"}
                            </TableCell>
                            <TableCell className="text-[10.5px]">
                              {calloutStrings.length === 0 ? (
                                <span className="text-slate-300">—</span>
                              ) : (
                                <div className="flex flex-wrap gap-1 max-w-[140px]">
                                  {calloutStrings.slice(0, 4).map((c, i) => (
                                    <span
                                      key={i}
                                      className="text-[9.5px] font-mono bg-amber-50 text-amber-700 border border-amber-200 rounded px-1 py-0.5"
                                      title={c}
                                    >
                                      {c.length > 14 ? `${c.slice(0, 12)}…` : c}
                                    </span>
                                  ))}
                                  {calloutStrings.length > 4 && (
                                    <span className="text-[9px] text-slate-400">+{calloutStrings.length - 4}</span>
                                  )}
                                </div>
                              )}
                            </TableCell>
                            <TableCell className="text-[10.5px] text-slate-500 font-mono">
                              {source ? source.replace(/_/g, " ") : <span className="text-slate-300">—</span>}
                            </TableCell>
                            <TableCell className="font-mono text-[11px]">
                              <span className={cn(
                                conf >= 0.9 ? "text-emerald-600" :
                                conf >= 0.7 ? "text-amber-500" : "text-red-500",
                              )}>
                                {(conf * 100).toFixed(0)}%
                              </span>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function formatDims(dims: Record<string, number | undefined> | null | undefined): string {
  if (!dims) return "—";
  const parts: string[] = [];
  if (dims.diameter_mm != null) parts.push(`Ø${dims.diameter_mm.toFixed(2)}`);
  if (dims.depth_mm    != null) parts.push(`d${dims.depth_mm.toFixed(2)}`);
  if (dims.width_mm    != null) parts.push(`w${dims.width_mm.toFixed(2)}`);
  if (dims.length_mm   != null) parts.push(`l${dims.length_mm.toFixed(2)}`);
  if (dims.radius_mm   != null) parts.push(`r${dims.radius_mm.toFixed(2)}`);
  return parts.join(" ") || JSON.stringify(dims).slice(0, 40);
}

// ---------------------------------------------------------------------------
// Processes tab — grouped by component
// ---------------------------------------------------------------------------

function ProcessesTab({ components }: { components: Component[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});

  return (
    <div className="space-y-2">
      {components.map((comp) => {
        const isOpen  = open[comp.component_index] ?? true;
        const procs = readProcesses(comp);
        const procCnt = procs.length;
        return (
          <div key={comp.component_index} className="rounded-xl border border-slate-200/60 overflow-hidden">
            <button
              className="w-full flex items-center gap-3 px-4 py-3 bg-slate-50/80 hover:bg-slate-50 transition-colors text-left"
              onClick={() => setOpen((p) => ({ ...p, [comp.component_index]: !isOpen }))}
            >
              <span className="w-5 h-5 rounded-md bg-amber-100 text-amber-700 text-[9px] font-mono font-bold flex items-center justify-center shrink-0">
                {comp.component_index}
              </span>
              <span className="text-[13px] font-semibold text-slate-800 flex-1 truncate">
                {comp.name || `Component ${comp.component_index}`}
              </span>
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="text-[10px] font-mono">{procCnt} ops</Badge>
                <span className="text-[10.5px] font-mono text-amber-700">
                  {comp.cycle_time_min != null ? `${comp.cycle_time_min.toFixed(1)} min` : "—"}
                </span>
                <span className="text-[10.5px] font-mono text-slate-600">
                  {comp.cost?.total_usd != null ? `$${comp.cost.total_usd.toFixed(2)}` : "—"}
                </span>
              </div>
              {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
            </button>

            {isOpen && procCnt > 0 && (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-white">
                      {[
                        "Seq", "Type", "Features", "Tool", "Machine",
                        "RPM", "Feed", "DOC (mm)", "Cut Len (mm)",
                        "Setup (min/lot)", "Run (min/part)",
                        "Total (min)", "Labor ($)", "Machine ($)", "Total ($)",
                      ].map((h) => (
                        <TableHead key={h} className="text-[10px] uppercase tracking-wider whitespace-nowrap">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {procs.map((p, idx) => {
                      const anyP = p as unknown as Record<string, unknown>;
                      const featIdx = (anyP.feature_indices as number[] | undefined) ?? [];
                      const setupMin = (anyP.setup_min_per_lot as number | undefined) ?? 0;
                      const runMin = (anyP.run_min_per_part as number | undefined) ?? 0;
                      const labor = (anyP.labor_role as string | undefined) ?? "";
                      const workCenter = (anyP.work_center as string | undefined) ?? "";
                      const notes = (p.notes as string | undefined) ?? "";
                      const doc = p.depth_of_cut_mm ?? 0;
                      const cutLen = p.cut_length_mm ?? 0;
                      const laborCost = p.labor_cost_usd ?? 0;
                      const machineCost = p.machine_cost_usd ?? 0;
                      const toolLabel =
                        p.tooling_ref?.tool_name?.trim() ||
                        (notes ? notes : "—");
                      const machineLabel =
                        p.machine_ref?.machine_name?.trim() ||
                        (workCenter ? workCenter.replace(/_/g, " ") : "—");
                      const totalMin = p.cycle_time_min ?? 0;
                      const seq = p.sequence_order ?? idx + 1;
                      return (
                        <TableRow key={`${comp.component_index}-${seq}-${idx}`}>
                          <TableCell className="font-mono text-[11px] text-slate-400">{seq}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px] font-mono border-slate-200 text-slate-600 whitespace-nowrap">
                              {p.process_type ?? "—"}
                            </Badge>
                            {labor && (
                              <div className="text-[9.5px] text-slate-400 mt-0.5 font-mono">{labor}</div>
                            )}
                          </TableCell>
                          <TableCell className="text-[11px]">
                            {featIdx.length === 0 ? (
                              <span className="text-slate-300">—</span>
                            ) : (
                              <div className="flex flex-wrap gap-1 max-w-[120px]">
                                {featIdx.slice(0, 6).map((fi: number) => (
                                  <span key={fi} className="text-[9px] font-mono bg-amber-50 text-amber-700 border border-amber-100 rounded px-1 py-0.5">
                                    F{fi}
                                  </span>
                                ))}
                                {featIdx.length > 6 && (
                                  <span className="text-[9px] text-slate-400">+{featIdx.length - 6}</span>
                                )}
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="text-[12px] text-slate-700 max-w-[160px] truncate" title={toolLabel}>{toolLabel}</TableCell>
                          <TableCell className="text-[12px] text-slate-500 max-w-[140px] truncate" title={machineLabel}>{machineLabel}</TableCell>
                          <TableCell className="font-mono text-[12px]">
                            {p.spindle_rpm ? p.spindle_rpm.toLocaleString() : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px]">
                            {p.feed_mm_per_min ? p.feed_mm_per_min.toLocaleString() : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-slate-600">
                            {doc > 0 ? doc.toFixed(2) : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-slate-600">
                            {cutLen > 0 ? cutLen.toLocaleString(undefined, { maximumFractionDigits: 1 }) : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-indigo-600">
                            {setupMin > 0 ? setupMin.toFixed(1) : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-slate-700">
                            {runMin > 0 ? runMin.toFixed(2) : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-amber-700 font-semibold">{totalMin.toFixed(2)}</TableCell>
                          <TableCell className="font-mono text-[12px] text-emerald-700">
                            {laborCost > 0 ? `$${laborCost.toFixed(2)}` : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] text-cyan-700">
                            {machineCost > 0 ? `$${machineCost.toFixed(2)}` : <span className="text-slate-300">—</span>}
                          </TableCell>
                          <TableCell className="font-mono text-[12px] font-semibold">${p.total_cost_usd?.toFixed(2) ?? "0.00"}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2D Extraction tab
// ---------------------------------------------------------------------------

function ExtractionTab({ result }: { result: FinalAnswer }) {
  const ext = result.vlm_extraction;
  if (!ext) return <EmptyNote text="No 2D extraction data available" />;

  return (
    <div className="space-y-6">
      {/* Title block */}
      <div>
        <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">Title Block</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {(() => {
            const baseRows = [
              { key: "part_number",    label: "Part Number",    value: ext.part_number    },
              { key: "revision",       label: "Revision",       value: ext.revision       },
              { key: "description",    label: "Description",    value: ext.description    },
              { key: "material",       label: "Material",       value: ext.material       },
              { key: "surface_finish", label: "Surface Finish", value: ext.surface_finish },
              { key: "dimension_unit", label: "Dimension Unit", value: ext.dimension_unit },
            ];
            const baseKeys = new Set(baseRows.map((r) => r.key));
            const tb = (ext.title_block ?? {}) as Record<string, unknown>;
            const extraRows = Object.entries(tb)
              .filter(([k, v]) => !baseKeys.has(k) && v !== null && v !== undefined && v !== "")
              .map(([k, v]) => ({
                key: k,
                label: k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                value: typeof v === "object" ? JSON.stringify(v) : String(v),
              }));
            return [...baseRows, ...extraRows].map((row) => (
              <div key={row.key} className="bg-slate-50 rounded-lg px-3 py-2.5 border border-slate-200/60">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide">{row.label}</div>
                <div className="text-[13px] font-medium text-slate-800 mt-0.5">{row.value || "—"}</div>
              </div>
            ));
          })()}
        </div>
      </div>

      <Separator />

      {/* BOM mapping */}
      <div>
        <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
          BOM ↔ Assembly Mapping
        </div>
        <BomMappingTable bomItems={ext.bom_items ?? []} components={result.components ?? []} />
      </div>

      {/* Drawing notes */}
      {(ext.drawing_notes?.length ?? 0) > 0 && (
        <>
          <Separator />
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">Drawing Notes</div>
            <ul className="space-y-1.5">
              {(ext.drawing_notes as any[]).map((n: any, i: number) => {
                const text =
                  typeof n === "string"
                    ? n
                    : n?.text ?? n?.note ?? n?.content ?? JSON.stringify(n);
                return (
                  <li key={i} className="flex gap-2 text-[12.5px] text-slate-700">
                    <span className="text-amber-400 shrink-0">·</span>
                    <span className="whitespace-pre-wrap">{text}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}

      {/* Dimensions */}
      {(ext.dimensions?.length ?? 0) > 0 && (
        <>
          <Separator />
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
              Dimensions ({ext.dimensions!.length})
            </div>
            <div className="rounded-xl border border-slate-200/60 overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50/80">
                    <TableHead className="text-[10px] uppercase tracking-wider">Feature</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Nominal</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Tolerance +</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Tolerance −</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Unit</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Qty</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(ext.dimensions as any[]).map((d: any, i: number) => {
                    const label =
                      d.label ??
                      d.feature ??
                      d.description ??
                      d.name;
                    const feature = d.id
                      ? (label ? `${d.id} · ${label}` : d.id)
                      : (label ?? "—");
                    return (
                      <TableRow key={i}>
                        <TableCell className="text-[12px]">{feature}</TableCell>
                        <TableCell className="font-mono text-[12px]">{d.nominal_mm ?? d.nominal ?? "—"}</TableCell>
                        <TableCell className="font-mono text-[11.5px] text-emerald-600">
                          {d.upper_mm != null ? `+${d.upper_mm}` : d.tolerance_plus != null ? `+${d.tolerance_plus}` : "—"}
                        </TableCell>
                        <TableCell className="font-mono text-[11.5px] text-red-500">
                          {d.lower_mm != null ? `${d.lower_mm}` : d.tolerance_minus != null ? `${d.tolerance_minus}` : "—"}
                        </TableCell>
                        <TableCell className="text-[11px] text-slate-400">{d.unit ?? "—"}</TableCell>
                        <TableCell className="font-mono text-[12px]">{d.quantity ?? 1}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
        </>
      )}

      {/* GD&T callouts */}
      {(ext.gdt_callouts?.length ?? 0) > 0 && (
        <>
          <Separator />
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
              GD&T Callouts ({ext.gdt_callouts!.length})
            </div>
            <div className="flex flex-wrap gap-2">
              {(ext.gdt_callouts as any[]).map((g: any, i: number) => (
                <div key={i} className="text-[11px] font-mono bg-slate-100 rounded-lg px-2.5 py-1.5 border border-slate-200">
                  <span className="font-semibold text-slate-700">{g.symbol ?? g.type}</span>
                  {g.tolerance != null && <span className="text-slate-500 ml-1">{g.tolerance}</span>}
                  {g.value != null && <span className="text-slate-500 ml-1">{g.value}</span>}
                  {g.unit && <span className="text-slate-400 ml-0.5">{g.unit}</span>}
                  {(g.datums?.length || g.datum_ref?.length || g.datum) && (
                    <span className="text-amber-600 ml-1.5">
                      |{Array.isArray(g.datums)
                        ? g.datums.join("|")
                        : Array.isArray(g.datum_ref)
                          ? g.datum_ref.join("|")
                          : g.datum}
                    </span>
                  )}
                  {g.feature && (
                    <span className="text-slate-400 ml-1.5">@{g.feature}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Threads */}
      {((ext.threads as any[] | undefined)?.length ?? 0) > 0 && (
        <>
          <Separator />
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
              Threads ({(ext.threads as any[]).length})
            </div>
            <div className="rounded-xl border border-slate-200/60 overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50/80">
                    <TableHead className="text-[10px] uppercase tracking-wider">Spec</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Qty</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Depth</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Through</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-wider">Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(ext.threads as any[]).map((t: any, i: number) => {
                    const spec   = t.designation ?? t.spec ?? t.size ?? t.thread ?? "—";
                    const qty    = t.qty  ?? t.count       ?? t.quantity  ?? 1;
                    const depth  = t.depth_mm ?? t.depth   ?? null;
                    const through= t.through ?? t.is_through ?? null;
                    const notes  = t.notes  ?? t.note      ?? t.description ?? "";
                    return (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-[12px] font-medium text-slate-800">{spec}</TableCell>
                        <TableCell className="font-mono text-[12px]">{qty}</TableCell>
                        <TableCell className="font-mono text-[12px]">{depth != null ? `${depth} mm` : "—"}</TableCell>
                        <TableCell className="text-[11.5px] text-slate-500">{through === true ? "yes" : through === false ? "no" : "—"}</TableCell>
                        <TableCell className="text-[11.5px] text-slate-500 max-w-[240px] truncate" title={notes}>{notes || "—"}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return (
    <div className="py-10 text-center text-[13px] text-slate-400">
      {text}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assembly info — PMI flag + welding contacts
// ---------------------------------------------------------------------------

function AssemblyInfoCard({ result }: { result: FinalAnswer }) {
  const ad = result.assembly_data;
  const welds = ad?.welding_contacts ?? [];
  const pmi = ad?.pmi_available ?? false;
  if (!ad || (welds.length === 0 && !pmi)) return null;

  return (
    <Card className="border-slate-200/60">
      <CardHeader className="pb-2">
        <CardTitle className="text-[13px] flex items-center gap-2">
          <Layers className="w-3.5 h-3.5 text-slate-500" />
          Assembly Data
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] font-mono",
              pmi
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-slate-200 bg-slate-50 text-slate-500",
            )}
          >
            PMI: {pmi ? "available" : "none"}
          </Badge>
          <Badge variant="outline" className="text-[10px] font-mono border-slate-200 text-slate-600">
            Welding contacts: {welds.length}
          </Badge>
        </div>
        {welds.length > 0 && (
          <div className="rounded-lg border border-slate-200/60 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50/70">
                  <TableHead className="text-[10px] uppercase tracking-wider">Component A</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider">Component B</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider">Type</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-right">Length (mm)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {welds.map((w, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-[12px] font-mono text-slate-700 truncate max-w-[180px]" title={w.comp_a}>{w.comp_a}</TableCell>
                    <TableCell className="text-[12px] font-mono text-slate-700 truncate max-w-[180px]" title={w.comp_b}>{w.comp_b}</TableCell>
                    <TableCell className="text-[11px] text-slate-500">{w.contact_type}</TableCell>
                    <TableCell className="text-[12px] font-mono text-right text-amber-700">{(w.contact_length_mm ?? 0).toFixed(1)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Compact summary fallback (when only the <id>.json note exists)
// ---------------------------------------------------------------------------

function isCompactNote(payload: unknown): payload is { analysis_id: string; written_at_epoch?: number; summary?: any; extra?: any } {
  if (!payload || typeof payload !== "object") return false;
  const p = payload as Record<string, unknown>;
  return "summary" in p && !("components" in p);
}

function CompactSummaryView({ note, analysisId }: { note: any; analysisId: string }) {
  const summary = note.summary ?? {};
  const components = (summary.components ?? []) as any[];
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/history">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="w-3.5 h-3.5" />
            History
          </Button>
        </Link>
        <span className="text-[11px] font-mono text-slate-500 ml-auto">{analysisId}</span>
      </div>
      <Card className="border-amber-200/60 bg-amber-50/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-[13px]">Summary only</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-[12px] text-slate-600">
            The full result file is no longer on disk for this analysis. The compact diagnostic note remains.
          </p>
        </CardContent>
      </Card>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card className="py-4">
          <CardContent className="px-4 text-center">
            <div className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Total USD</div>
            <div className="text-xl font-bold font-mono mt-1">{summary.total_usd != null ? `$${summary.total_usd.toFixed(2)}` : "—"}</div>
          </CardContent>
        </Card>
        <Card className="py-4">
          <CardContent className="px-4 text-center">
            <div className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Components</div>
            <div className="text-xl font-bold font-mono mt-1">{summary.n_components ?? components.length}</div>
          </CardContent>
        </Card>
        <Card className="py-4">
          <CardContent className="px-4 text-center">
            <div className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Routing Rows</div>
            <div className="text-xl font-bold font-mono mt-1">{summary.n_routing_rows ?? "—"}</div>
          </CardContent>
        </Card>
        <Card className="py-4">
          <CardContent className="px-4 text-center">
            <div className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Created</div>
            <div className="text-[12px] font-mono mt-1">{note.written_at_epoch ? new Date(note.written_at_epoch * 1000).toLocaleString() : "—"}</div>
          </CardContent>
        </Card>
      </div>
      {components.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-[13px]">Components (diagnostic)</CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px] uppercase tracking-wider">#</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider">Name</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider">Part Type</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider">Machine</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-wider text-right">Run/Setup (min)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {components.map((c: any) => (
                  <TableRow key={c.component_index}>
                    <TableCell className="font-mono text-[11px] text-slate-400">{c.component_index}</TableCell>
                    <TableCell className="text-[12px]">{c.name ?? "—"}</TableCell>
                    <TableCell className="text-[11.5px]">{c.part_type ?? "—"}</TableCell>
                    <TableCell className="text-[11.5px] font-mono">{c.chosen_machine_id ?? c.machine_class ?? "—"}</TableCell>
                    <TableCell className="text-right font-mono text-[11.5px]">
                      {c.total_run_min_per_part != null ? `${Number(c.total_run_min_per_part).toFixed(1)}` : "—"}
                      {" / "}
                      {c.setup_min_per_lot != null ? `${Number(c.setup_min_per_lot).toFixed(1)}` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main A4 detail view
// ---------------------------------------------------------------------------

interface Props {
  result: FinalAnswer | Record<string, unknown>;
  analysisId: string;
}

export function A4DetailView({ result, analysisId }: Props) {
  const searchParams = useSearchParams();
  const compParam    = searchParams.get("comp");
  const [selectedComp, setSelectedComp] = useState<number | undefined>(
    compParam != null ? parseInt(compParam) : undefined
  );

  const router = useRouter();

  // Compact-note fallback when the full result file is missing
  if (isCompactNote(result)) {
    return <CompactSummaryView note={result} analysisId={analysisId} />;
  }

  const fa = result as FinalAnswer;
  const components = fa.components ?? [];

  const totalFeats = components.reduce((s, c) => s + (c.features?.length ?? 0), 0);
  const totalProcs = components.reduce((s, c) => s + readProcesses(c).length, 0);

  const handleCompSelect = (idx: number) => {
    setSelectedComp(idx);
    const url = new URL(window.location.href);
    url.searchParams.set("comp", String(idx));
    router.replace(url.pathname + url.search, { scroll: false });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/history">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="w-3.5 h-3.5" />
            History
          </Button>
        </Link>
        <div className="ml-auto flex items-center gap-2">
          {fa.file_name && (
            <span className="text-[11px] font-mono text-slate-500 truncate max-w-[200px]">{fa.file_name}</span>
          )}
        </div>
      </div>

      {fa.assembly_name && (
        <div>
          <h1 className="text-[22px] font-bold tracking-tight text-slate-900">{fa.assembly_name}</h1>
        </div>
      )}

      <SummaryCards result={fa} />
      <AssemblyInfoCard result={fa} />

      <Separator />

      <Tabs defaultValue="components">
        <TabsList className="flex-wrap h-auto gap-1">
          <TabsTrigger value="components">
            Components ({components.length})
          </TabsTrigger>
          <TabsTrigger value="features">
            Features ({totalFeats})
          </TabsTrigger>
          <TabsTrigger value="processes">
            Processes ({totalProcs})
          </TabsTrigger>
          <TabsTrigger value="cost">Cost Breakdown</TabsTrigger>
          <TabsTrigger value="extraction">2D Extraction</TabsTrigger>
        </TabsList>

        <TabsContent value="components" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="lg:col-span-1">
              <ComponentTree
                components={components}
                selectedIndex={selectedComp}
                onSelect={handleCompSelect}
              />
            </div>
            <div className="lg:col-span-2 space-y-4">
              {selectedComp != null && (() => {
                const comp = components.find((c) => c.component_index === selectedComp);
                if (!comp) return null;
                return (
                  <Card className="border-amber-200/40">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-[14px]">
                        {comp.name || `Component ${comp.component_index}`}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3 text-[12.5px]">
                      <div className="grid grid-cols-2 gap-3">
                        {(() => {
                          const t = comp.thickness;
                          let thicknessLabel = "—";
                          if (t && (t.min_mm || t.max_mm || t.mean_mm)) {
                            if (t.is_uniform && t.mean_mm) {
                              thicknessLabel = `${t.mean_mm.toFixed(2)} mm`;
                            } else if (t.min_mm && t.max_mm) {
                              thicknessLabel = `${t.min_mm.toFixed(2)}–${t.max_mm.toFixed(2)} mm`;
                            } else if (t.mean_mm) {
                              thicknessLabel = `${t.mean_mm.toFixed(2)} mm avg`;
                            }
                          }
                          const rows = [
                            { label: "Part Type",    value: comp.part_type?.replace(/_/g, " ")  },
                            { label: "Material",     value: comp.material                       },
                            { label: "Instances",    value: comp.instance_count != null ? `${comp.instance_count}×` : "—" },
                            { label: "Thickness",    value: thicknessLabel                      },
                            { label: "Volume",       value: comp.volume_mm3 ? `${comp.volume_mm3.toFixed(0)} mm³` : "—" },
                            { label: "Surface Area", value: comp.surface_area_mm2 ? `${comp.surface_area_mm2.toFixed(0)} mm²` : "—" },
                            { label: "Cycle Time",   value: comp.cycle_time_min ? `${comp.cycle_time_min.toFixed(2)} min` : "—" },
                            { label: "Cost",         value: comp.cost?.total_usd != null ? `$${comp.cost.total_usd.toFixed(2)}` : "—" },
                          ];
                          return rows.map((r) => (
                            <div key={r.label} className="bg-slate-50 rounded-lg px-3 py-2 border border-slate-100">
                              <div className="text-[10px] text-slate-400 uppercase tracking-wide font-semibold">{r.label}</div>
                              <div className="font-mono font-medium text-slate-800 mt-0.5">{r.value || "—"}</div>
                            </div>
                          ));
                        })()}
                      </div>
                      {comp.bbox && (
                        <div className="bg-amber-50 rounded-lg px-3 py-2 border border-amber-100 font-mono text-[12px] text-amber-800">
                          BBox: {comp.bbox.length_mm?.toFixed(1)} × {comp.bbox.width_mm?.toFixed(1)} × {comp.bbox.height_mm?.toFixed(1)} mm
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })()}
              {selectedComp == null && (
                <div className="flex items-center justify-center h-40 rounded-xl border border-dashed border-slate-200 text-[12px] text-slate-400">
                  Select a component to view details
                </div>
              )}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="features" className="mt-4">
          <FeaturesTab components={components} />
        </TabsContent>

        <TabsContent value="processes" className="mt-4">
          <ProcessesTab components={components} />
        </TabsContent>

        <TabsContent value="cost" className="mt-4">
          <Card className="p-5">
            <CardHeader className="px-0 pt-0 pb-4">
              <CardTitle className="text-[14px]">Cost Breakdown</CardTitle>
            </CardHeader>
            <CardContent className="px-0">
              <CostBreakdown components={components} batchSize={fa.batch_size ?? 1} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="extraction" className="mt-4">
          <ExtractionTab result={fa} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
