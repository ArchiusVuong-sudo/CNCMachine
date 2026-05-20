"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Timer, DollarSign, Layers, Wrench } from "lucide-react";

interface SummaryCardsProps {
  totalMinutes: number;
  totalUsd: number;
  featureCount: number;
  operationCount: number;
}

export function SummaryCards({ totalMinutes, totalUsd, featureCount, operationCount }: SummaryCardsProps) {
  const cards = [
    {
      label: "Cycle Time",
      value: totalMinutes.toFixed(1),
      unit: "min",
      icon: Timer,
      accent: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
    },
    {
      label: "Total Cost",
      value: `$${totalUsd.toFixed(2)}`,
      unit: "USD",
      icon: DollarSign,
      accent: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    },
    {
      label: "Features",
      value: String(featureCount),
      unit: "detected",
      icon: Layers,
      accent: "text-blue-400 bg-blue-500/10 border-blue-500/20",
    },
    {
      label: "Operations",
      value: String(operationCount),
      unit: "mapped",
      icon: Wrench,
      accent: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((c) => (
        <Card key={c.label} className={`rounded-xl border p-4 ${c.accent}`}>
          <CardContent className="p-0 flex items-start gap-3">
            <div className={`mt-0.5 ${c.accent.split(" ")[0]}`}>
              <c.icon className="w-5 h-5" />
            </div>
            <div>
              <div className="text-2xl font-bold font-mono leading-none">{c.value}</div>
              <div className="text-[10px] mt-1 opacity-70 font-mono">{c.unit}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{c.label}</div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
