"use client";

import { PieChart, Pie, Cell, Tooltip as ChartTooltip, ResponsiveContainer } from "recharts";
import type { CanvasComponent } from "@/lib/hooks/useApproach4";

interface Props {
  components: Record<number, CanvasComponent>;
}

const PALETTE = ["#6366f1", "#06b6d4", "#10b981", "#f59e0b", "#f97316", "#ec4899", "#84cc16", "#a855f7", "#3b82f6", "#ef4444"];

function pretty(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ProcessDistributionChart({ components }: Props) {
  const counts = new Map<string, number>();
  let total = 0;
  for (const comp of Object.values(components)) {
    for (const p of comp.processes ?? []) {
      const key = p.process_type || "other";
      counts.set(key, (counts.get(key) || 0) + 1);
      total += 1;
    }
  }
  const items = Array.from(counts.entries())
    .map(([name, value]) => ({ name: pretty(name), value }))
    .sort((a, b) => b.value - a.value);

  if (items.length === 0 || total === 0) {
    return (
      <div className="h-[220px] flex items-center justify-center text-[11.5px] text-slate-400 border border-dashed border-slate-200 rounded-lg">
        No processes selected yet
      </div>
    );
  }

  return (
    <div className="w-full flex flex-col gap-2">
      <div className="w-full h-[170px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={items}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={42}
              outerRadius={72}
              paddingAngle={2}
              stroke="#fff"
              strokeWidth={1.5}
            >
              {items.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
            <ChartTooltip
              contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
              formatter={(v, name) => {
                const num = Number(v);
                return [`${num} op${num === 1 ? "" : "s"}`, String(name ?? "")] as [string, string];
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] px-1">
        {items.map((item, i) => {
          const pct = ((item.value / total) * 100).toFixed(0);
          return (
            <li
              key={item.name}
              className="inline-flex items-center gap-1.5 min-w-0 max-w-[180px]"
              title={`${item.name} · ${item.value} op${item.value === 1 ? "" : "s"} (${pct}%)`}
            >
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{ background: PALETTE[i % PALETTE.length] }}
              />
              <span className="text-slate-600 truncate">{item.name}</span>
              <span className="text-slate-400 font-mono shrink-0">· {pct}%</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
