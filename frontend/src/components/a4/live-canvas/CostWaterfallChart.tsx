"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer, Cell } from "recharts";
import type { ComponentCost } from "@/lib/api/types";

interface Props {
  cost?: ComponentCost | null;
}

const SEGMENT_LABELS: Record<string, string> = {
  raw_material: "Raw Material",
  setup:        "Setup",
  cnc_milling:  "CNC Milling",
  cnc_turning:  "CNC Turning",
  drilling:     "Drilling",
  tapping:      "Tapping",
  threading:    "Threading",
  laser_cutting:"Laser Cut",
  press_brake:  "Press Brake",
  deburring:    "Deburring",
  inspection:   "Inspection",
  assembly:     "Assembly",
  part_mark:    "Part Mark",
  outsourced:   "Vendor",
  packaging:    "Packaging",
};

const PALETTE = ["#6366f1", "#8b5cf6", "#3b82f6", "#06b6d4", "#0ea5e9", "#10b981", "#f59e0b", "#f97316", "#ef4444", "#ec4899"];

function label(key: string): string {
  return SEGMENT_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function CostWaterfallChart({ cost }: Props) {
  if (!cost) {
    return <EmptyChart message="No cost data yet" />;
  }

  const rows: { name: string; value: number }[] = [];
  if (cost.raw_material_usd > 0) rows.push({ name: label("raw_material"), value: cost.raw_material_usd });
  if (cost.setup_usd > 0)        rows.push({ name: label("setup"),        value: cost.setup_usd });
  for (const [k, v] of Object.entries(cost.machining_usd_by_process || {})) {
    const num = Number(v);
    if (Number.isFinite(num) && num > 0.001) rows.push({ name: label(k), value: num });
  }
  if (cost.deburr_usd > 0 && !rows.find((r) => r.name === label("deburring"))) {
    rows.push({ name: label("deburring"), value: cost.deburr_usd });
  }
  if (cost.inspection_usd > 0 && !rows.find((r) => r.name === label("inspection"))) {
    rows.push({ name: label("inspection"), value: cost.inspection_usd });
  }

  if (rows.length === 0) return <EmptyChart message="No cost segments" />;

  rows.sort((a, b) => b.value - a.value);

  return (
    <div className="w-full h-[220px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 4 }}>
          <CartesianGrid horizontal={false} stroke="#e5e7eb" strokeDasharray="2 2" />
          <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => `$${v.toFixed(2)}`} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 10.5, fill: "#475569" }} width={92} />
          <ChartTooltip
            cursor={{ fill: "#f1f5f9" }}
            contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
            formatter={(v) => [`$${Number(v).toFixed(2)}`, "Cost"] as [string, string]}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {rows.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="h-[220px] flex items-center justify-center text-[11.5px] text-slate-400 border border-dashed border-slate-200 rounded-lg">
      {message}
    </div>
  );
}
