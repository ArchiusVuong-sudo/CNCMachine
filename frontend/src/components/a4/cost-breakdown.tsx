"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Component } from "@/lib/api/types";

interface Props {
  components: Component[];
  batchSize?: number;
}

const SEGMENT_META: Array<{ key: string; label: string; color: string }> = [
  { key: "raw_material",      label: "Raw Material",   color: "bg-slate-400"   },
  { key: "setup",             label: "Setup",          color: "bg-indigo-400"  },
  { key: "cnc_milling",       label: "CNC Milling",    color: "bg-blue-600"    },
  { key: "3_axis_milling",    label: "3-Axis Milling", color: "bg-blue-500"    },
  { key: "4_axis_milling",    label: "4-Axis Milling", color: "bg-blue-700"    },
  { key: "5_axis_milling",    label: "5-Axis Milling", color: "bg-blue-800"    },
  { key: "cnc_turning",       label: "CNC Turning",    color: "bg-indigo-600"  },
  { key: "turning_rough",     label: "Turning Rough",  color: "bg-indigo-500"  },
  { key: "turning_finish",    label: "Turning Finish", color: "bg-indigo-700"  },
  { key: "drilling",          label: "Drilling",       color: "bg-sky-500"     },
  { key: "tapping",           label: "Tapping",        color: "bg-sky-400"     },
  { key: "threading",         label: "Threading",      color: "bg-sky-600"     },
  { key: "laser_cutting",     label: "Laser Cutting",  color: "bg-cyan-500"    },
  { key: "press_brake",       label: "Press Brake",    color: "bg-cyan-600"    },
  { key: "welding",           label: "Welding",        color: "bg-orange-500"  },
  { key: "deburring",         label: "Deburring",      color: "bg-purple-400"  },
  { key: "manual_deburring",  label: "Manual Deburr",  color: "bg-purple-500"  },
  { key: "inspection",        label: "Inspection",     color: "bg-pink-400"    },
  { key: "cmm_measurement",   label: "CMM",            color: "bg-pink-500"    },
  { key: "assembly",          label: "Assembly",       color: "bg-teal-500"    },
  { key: "part_mark",         label: "Part Mark",      color: "bg-lime-500"    },
  { key: "outsourced",        label: "Vendor Op",      color: "bg-rose-400"    },
  { key: "packaging",         label: "Packaging",      color: "bg-stone-400"   },
  { key: "overhead",          label: "Overhead",       color: "bg-amber-300"   },
  { key: "other",             label: "Other Ops",      color: "bg-blue-400"    },
];

const SEGMENT_COLOR: Record<string, string> = Object.fromEntries(
  SEGMENT_META.map((s) => [s.key, s.color]),
);
const SEGMENT_LABEL: Record<string, string> = Object.fromEntries(
  SEGMENT_META.map((s) => [s.key, s.label]),
);
const SEGMENT_ORDER: Record<string, number> = Object.fromEntries(
  SEGMENT_META.map((s, i) => [s.key, i]),
);

function prettyKey(key: string): string {
  if (SEGMENT_LABEL[key]) return SEGMENT_LABEL[key];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function buildSegmentMap(comp: Component, multiplier: number): Record<string, number> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cost = comp.cost as any;
  if (!cost) return {};

  const raw: Record<string, number> = {};

  const rawMat = Number(cost.raw_material_usd ?? 0);
  if (rawMat > 0) raw.raw_material = rawMat;

  const setupTop = Number(cost.setup_usd ?? 0);
  if (setupTop > 0) raw.setup = setupTop;

  const machMap = (cost.machining_usd_by_process ?? {}) as Record<string, number>;
  for (const [k, v] of Object.entries(machMap)) {
    const amt = Number(v ?? 0);
    if (!Number.isFinite(amt) || amt <= 0) continue;
    raw[k] = (raw[k] ?? 0) + amt;
  }

  const legacyDeburr = Number(cost.deburr_usd ?? 0);
  if (legacyDeburr > 0 && !raw.deburring) raw.deburring = legacyDeburr;
  const legacyInsp = Number(cost.inspection_usd ?? 0);
  if (legacyInsp > 0 && !raw.inspection) raw.inspection = legacyInsp;

  // Overhead is a first-class waterfall row — without it the per-process
  // shares don't add up to cost.total_usd and the UI looks like it's hiding
  // money. We show it explicitly so the customer can see the 15% markup.
  const overhead = Number(cost.overhead_usd ?? 0);
  if (overhead > 0) raw.overhead = overhead;

  const scaled: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw)) {
    const s = v * multiplier;
    if (s > 0.001) scaled[k] = s;
  }
  return scaled;
}

interface ComponentRow {
  index: number;
  name:  string;
  map:   Record<string, number>;
  total: number;
}

export function CostBreakdown({ components, batchSize = 1 }: Props) {
  const [perBatch, setPerBatch] = useState(false);
  const multiplier = perBatch ? (batchSize ?? 1) : 1;

  if (!components?.length) {
    return <div className="text-sm text-slate-400 py-6 text-center font-mono">No cost data</div>;
  }

  const rows: ComponentRow[] = components.map((c) => {
    const map = buildSegmentMap(c, multiplier);
    const total = Object.values(map).reduce((s, v) => s + v, 0);
    return {
      index: c.component_index,
      name:  c.name || `C${c.component_index}`,
      map,
      total,
    };
  }).sort((a, b) => a.index - b.index);

  // Process-type totals across the whole assembly
  const processTotals: Record<string, number> = {};
  for (const r of rows) {
    for (const [k, v] of Object.entries(r.map)) {
      processTotals[k] = (processTotals[k] ?? 0) + v;
    }
  }
  const grandTotal = Object.values(processTotals).reduce((s, v) => s + v, 0);

  // Process types that actually carry money, biggest spend first
  const processTypes = Object.entries(processTotals)
    .filter(([, v]) => v > 0.001)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k);

  if (processTypes.length === 0 || grandTotal <= 0.001) {
    return (
      <div className="py-10 text-center text-[12.5px] text-slate-500 border border-dashed rounded-xl">
        No cost data yet. Run the analysis to see the breakdown.
      </div>
    );
  }

  const topProcessKey = processTypes[0];
  const topProcessPct = (processTotals[topProcessKey] / grandTotal) * 100;

  return (
    <div className="space-y-5">
      {/* Toggle + headline tiles ─────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className={cn("text-[11px] font-semibold", !perBatch ? "text-slate-800" : "text-slate-400")}>
            Per part
          </span>
          <button
            onClick={() => setPerBatch((v) => !v)}
            aria-label="Toggle per-part vs batch total"
            className={cn(
              "relative w-10 h-5 rounded-full transition-colors",
              perBatch ? "bg-amber-500" : "bg-slate-200",
            )}
          >
            <span className={cn(
              "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
              perBatch ? "translate-x-5" : "translate-x-0.5",
            )} />
          </button>
          <span className={cn("text-[11px] font-semibold", perBatch ? "text-amber-700" : "text-slate-400")}>
            Batch ×{batchSize}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-amber-600/70 font-mono">Total</div>
            <div className="text-[14px] font-bold font-mono text-amber-800">${grandTotal.toFixed(2)}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-slate-400 font-mono">Top driver</div>
            <div className="text-[12px] font-semibold text-slate-700">
              {prettyKey(topProcessKey)}
              <span className="ml-1.5 text-[10.5px] font-mono text-slate-400">{topProcessPct.toFixed(0)}%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Two-panel layout ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-5">

        {/* LEFT — process-type summary */}
        <div className="xl:col-span-2 space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Where the money goes
          </div>
          <div className="rounded-xl border border-slate-200 overflow-hidden">
            <table className="w-full text-[11.5px]">
              <thead className="bg-slate-50">
                <tr className="text-left text-[9.5px] uppercase tracking-wider text-slate-500">
                  <th className="px-3 py-2 font-semibold">Process</th>
                  <th className="px-3 py-2 font-semibold text-right">USD</th>
                  <th className="px-3 py-2 font-semibold w-[42%]">Share</th>
                </tr>
              </thead>
              <tbody>
                {processTypes.map((k) => {
                  const v   = processTotals[k];
                  const pct = (v / grandTotal) * 100;
                  return (
                    <tr key={k} className="border-t border-slate-100 hover:bg-slate-50/50">
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className={cn("w-2 h-2 rounded-sm shrink-0", SEGMENT_COLOR[k] ?? "bg-slate-400")} />
                          <span className="text-slate-700">{prettyKey(k)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-700">${v.toFixed(2)}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <div className="relative h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
                            <div
                              className={cn("absolute inset-y-0 left-0 rounded-full", SEGMENT_COLOR[k] ?? "bg-slate-400")}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-mono text-slate-500 w-9 text-right">
                            {pct.toFixed(1)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot className="bg-amber-50/40 border-t-2 border-amber-200">
                <tr>
                  <td className="px-3 py-2 font-bold text-slate-800 text-[11.5px]">Total</td>
                  <td className="px-3 py-2 text-right font-mono font-bold text-amber-800 text-[12px]">
                    ${grandTotal.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-[10px] text-slate-500">100%</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        {/* RIGHT — per-component pivot */}
        <div className="xl:col-span-3 space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            By component ({rows.length})
          </div>
          <div className="rounded-xl border border-slate-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-[11.5px] border-collapse">
                <thead className="bg-slate-50">
                  <tr className="text-left text-[9.5px] uppercase tracking-wider text-slate-500">
                    <th className="px-3 py-2 font-semibold sticky left-0 bg-slate-50 z-10 min-w-[180px]">
                      Component
                    </th>
                    {processTypes.map((k) => (
                      <th key={k} className="px-2.5 py-2 font-semibold text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1.5">
                          <span className={cn("w-1.5 h-1.5 rounded-sm", SEGMENT_COLOR[k] ?? "bg-slate-400")} />
                          {prettyKey(k)}
                        </div>
                      </th>
                    ))}
                    <th className="px-3 py-2 font-semibold text-right bg-amber-50/40 whitespace-nowrap">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.index} className="border-t border-slate-100 hover:bg-slate-50/50">
                      <td className="px-3 py-2 sticky left-0 bg-white z-10 truncate max-w-[260px]">
                        <span className="text-[9px] font-mono text-slate-400 mr-2">#{row.index}</span>
                        <span className="text-slate-700 font-medium">{row.name}</span>
                      </td>
                      {processTypes.map((k) => {
                        const v = row.map[k] ?? 0;
                        return (
                          <td
                            key={k}
                            className={cn(
                              "px-2.5 py-2 text-right font-mono whitespace-nowrap",
                              v > 0 ? "text-slate-700" : "text-slate-300",
                            )}
                          >
                            {v > 0 ? `$${v.toFixed(2)}` : "—"}
                          </td>
                        );
                      })}
                      <td className="px-3 py-2 text-right font-mono font-semibold text-amber-800 bg-amber-50/40 whitespace-nowrap">
                        ${row.total.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-amber-50/40 border-t-2 border-amber-200">
                  <tr>
                    <td className="px-3 py-2 font-bold text-slate-800 sticky left-0 bg-amber-50/80 z-10">
                      Total
                    </td>
                    {processTypes.map((k) => (
                      <td key={k} className="px-2.5 py-2 text-right font-mono font-semibold text-slate-700 whitespace-nowrap">
                        ${(processTotals[k] ?? 0).toFixed(2)}
                      </td>
                    ))}
                    <td className="px-3 py-2 text-right font-mono font-bold text-amber-800 whitespace-nowrap">
                      ${grandTotal.toFixed(2)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
