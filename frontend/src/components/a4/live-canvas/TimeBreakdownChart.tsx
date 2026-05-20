"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer, Cell } from "recharts";
import type { RoutingRow } from "@/lib/api/types";

interface Props {
  processes?: RoutingRow[];
}

const PALETTE = ["#8b5cf6", "#3b82f6", "#06b6d4", "#10b981", "#f59e0b", "#f97316", "#ec4899", "#ef4444"];

const SHORT_LABELS: Record<string, string> = {
  raw_material:           "Raw Material",
  setup:                  "Setup",
  cnc_milling:            "CNC Mill",
  cnc_milling_finishing:  "CNC Mill Fin.",
  cnc_milling_roughing:   "CNC Mill Rgh.",
  cnc_turning:            "CNC Turn",
  cnc_grinding:           "CNC Grind",
  drilling:               "Drilling",
  tapping:                "Tapping",
  threading:              "Threading",
  laser_cutting:          "Laser Cut",
  press_brake:            "Press Brake",
  deburring:              "Deburring",
  inspection:             "Inspection",
  assembly:               "Assembly",
  welding:                "Welding",
  part_mark:              "Part Mark",
  outsourced:             "Vendor",
  packaging:              "Packaging",
};

function prettyProcess(name: string): string {
  if (SHORT_LABELS[name]) return SHORT_LABELS[name];
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function TimeBreakdownChart({ processes }: Props) {
  if (!processes || processes.length === 0) {
    return (
      <div className="h-[220px] flex items-center justify-center text-[11.5px] text-slate-400 border border-dashed border-slate-200 rounded-lg">
        No process data yet
      </div>
    );
  }

  // Aggregate by process_type
  const agg = new Map<string, number>();
  for (const p of processes) {
    const minutes = Number(p.cycle_time_min) || 0;
    if (minutes <= 0) continue;
    const key = p.process_type || "other";
    agg.set(key, (agg.get(key) || 0) + minutes);
  }
  const rows = Array.from(agg.entries())
    .map(([name, minutes]) => ({ name: prettyProcess(name), minutes }))
    .sort((a, b) => b.minutes - a.minutes);

  if (rows.length === 0) {
    return (
      <div className="h-[220px] flex items-center justify-center text-[11.5px] text-slate-400 border border-dashed border-slate-200 rounded-lg">
        No cycle time recorded
      </div>
    );
  }

  const height = Math.max(140, rows.length * 26 + 24);

  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke="#e5e7eb" strokeDasharray="2 2" />
          <XAxis
            type="number"
            tick={{ fontSize: 10, fill: "#64748b" }}
            tickFormatter={(v) => `${v.toFixed(1)}m`}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ fontSize: 10.5, fill: "#475569" }}
            width={92}
            interval={0}
          />
          <ChartTooltip
            cursor={{ fill: "#f1f5f9" }}
            contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
            formatter={(v) => [`${Number(v).toFixed(2)} min`, "Cycle time"] as [string, string]}
          />
          <Bar dataKey="minutes" radius={[0, 4, 4, 0]}>
            {rows.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
