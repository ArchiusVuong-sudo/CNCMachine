"use client";

import { PieChart, Pie, Cell, Tooltip as ChartTooltip, ResponsiveContainer } from "recharts";
import type { CanvasComponent } from "@/lib/hooks/useApproach4";

interface Props {
  components: Record<number, CanvasComponent>;
  activeIndex?: number;
}

const PALETTE = ["#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#f97316", "#06b6d4", "#ec4899", "#84cc16", "#f43f5e", "#a855f7"];

export function CostContributionChart({ components, activeIndex }: Props) {
  const items = Object.values(components)
    .map((c) => ({
      name:  c.name || `C${c.index}`,
      value: Number(c.totalUsd || c.cost?.total_usd || 0),
      index: c.index,
    }))
    .filter((r) => r.value > 0.001)
    .sort((a, b) => a.index - b.index);

  const total = items.reduce((s, r) => s + r.value, 0);

  if (items.length === 0 || total <= 0.001) {
    return (
      <div className="h-[220px] flex items-center justify-center text-[11.5px] text-slate-400 border border-dashed border-slate-200 rounded-lg">
        Waiting for component costs…
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
              {items.map((r, i) => (
                <Cell
                  key={i}
                  fill={PALETTE[r.index % PALETTE.length]}
                  opacity={activeIndex == null || r.index === activeIndex ? 1 : 0.35}
                />
              ))}
            </Pie>
            <ChartTooltip
              contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
              formatter={(v, _name, item) => {
                const num = Number(v);
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const label = (item as any)?.payload?.name ?? "";
                return [
                  `$${num.toFixed(2)} (${((num / total) * 100).toFixed(1)}%)`,
                  String(label),
                ] as [string, string];
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Custom legend below the chart — long component names get truncated
          with a hover tooltip showing the full text. */}
      <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] px-1">
        {items.map((item) => {
          const pct = ((item.value / total) * 100).toFixed(0);
          const isActive = item.index === activeIndex;
          return (
            <li
              key={item.index}
              className="inline-flex items-center gap-1.5 min-w-0 max-w-[160px]"
              title={`${item.name} · $${item.value.toFixed(2)} (${pct}%)`}
            >
              <span
                className="inline-block w-2 h-2 rounded-full shrink-0"
                style={{ background: PALETTE[item.index % PALETTE.length] }}
              />
              <span className={isActive ? "text-slate-900 font-medium truncate" : "text-slate-600 truncate"}>
                {item.name}
              </span>
              <span className="text-slate-400 font-mono shrink-0">· {pct}%</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
