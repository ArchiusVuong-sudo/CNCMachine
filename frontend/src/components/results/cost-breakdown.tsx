"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

interface BreakdownItem {
  line?: string;
  process?: string;
  amount_usd?: number;
  minutes?: number;
  category?: string;
}

interface CostBreakdownProps {
  title: string;
  items: BreakdownItem[];
  total: string;
  unit: string;
}

const CAT_COLORS: Record<string, string> = {
  material: "bg-emerald-500",
  setup: "bg-blue-500",
  machining: "bg-orange-500",
  overhead: "bg-purple-500",
  tool_change: "bg-gray-400",
};

export function CostBreakdownCard({ title, items, total, unit }: CostBreakdownProps) {
  const maxVal = Math.max(...items.map((i) => i.amount_usd || i.minutes || 0), 0.01);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">{title}</CardTitle>
          <span className="text-lg font-bold">{total} {unit}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item, i) => {
          const val = item.amount_usd || item.minutes || 0;
          const label = item.line || item.process || "";
          const pct = (val / maxVal) * 100;
          const cat = item.category || "machining";

          return (
            <div key={i}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground truncate mr-2">{label}</span>
                <span className="font-mono font-medium whitespace-nowrap">
                  {item.amount_usd !== undefined ? `$${val.toFixed(2)}` : `${val.toFixed(2)} min`}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${CAT_COLORS[cat] || "bg-primary"}`}
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>
            </div>
          );
        })}
        <Separator className="my-1" />
        <div className="flex items-center justify-between text-sm font-semibold">
          <span>Total</span>
          <span>{total} {unit}</span>
        </div>
      </CardContent>
    </Card>
  );
}
