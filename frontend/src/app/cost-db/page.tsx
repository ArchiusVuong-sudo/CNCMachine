"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Database,
  Box,
  Settings2,
  Drill,
  Users,
  ChevronRight,
  AlertCircle,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";

interface CategoryStats { total: number; active: number; }
type CatalogStats = Record<"material_stock" | "machines" | "tooling" | "labor_rates", CategoryStats>;

const CATEGORIES = [
  {
    key:   "material_stock" as const,
    label: "Material Stock",
    desc:  "Raw stock inventory with form, dimensions, and cost per piece.",
    icon:  Box,
    color: "from-amber-50 to-amber-100/50 border-amber-200/60",
    iconBg:"bg-amber-100 text-amber-600",
    href:  "/cost-db/material-stock",
  },
  {
    key:   "machines" as const,
    label: "Machines",
    desc:  "CNC machines with work envelope, spindle specs, and hourly rate.",
    icon:  Settings2,
    color: "from-indigo-50 to-indigo-100/50 border-indigo-200/60",
    iconBg:"bg-indigo-100 text-indigo-600",
    href:  "/cost-db/machines",
  },
  {
    key:   "tooling" as const,
    label: "Tooling",
    desc:  "Cutting tools with geometry, material, coating, and expected life.",
    icon:  Drill,
    color: "from-blue-50 to-blue-100/50 border-blue-200/60",
    iconBg:"bg-blue-100 text-blue-600",
    href:  "/cost-db/tooling",
  },
  {
    key:   "labor_rates" as const,
    label: "Labor Rates",
    desc:  "Operator role rates ($/hr) used in cost calculations.",
    icon:  Users,
    color: "from-purple-50 to-purple-100/50 border-purple-200/60",
    iconBg:"bg-purple-100 text-purple-600",
    href:  "/cost-db/labor",
  },
] as const;

function tally(rows: { is_active?: boolean }[]): CategoryStats {
  const total = rows.length;
  const active = rows.filter((r) => r.is_active === true).length;
  return { total, active };
}

export default function CostDbPage() {
  const [stats,   setStats]   = useState<CatalogStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [machines, tooling, laborRates, materialStock] = await Promise.all([
        api.listMachines(),
        api.listTooling(),
        api.listLaborRates(),
        api.listMaterialStock(),
      ]);
      setStats({
        material_stock: tally(materialStock),
        machines:       tally(machines),
        tooling:        tally(tooling),
        labor_rates:    tally(laborRates),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  return (
    <div className="max-w-3xl mx-auto py-8 px-4 space-y-8">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
            <Database className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-slate-900">Cost Database</h1>
            <p className="text-[13px] text-slate-500">
              Catalog tables consumed by the cost engine for each analysis.
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-200/60 rounded-full px-3 py-1.5">
              <Sparkles className="w-3 h-3" />
              Live
            </span>
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-[13px]">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          const s = stats ? stats[cat.key] : null;

          return (
            <Link key={cat.key} href={cat.href}>
              <Card className={cn(
                "group hover:shadow-[0_4px_16px_0_rgb(0,0,0,0.08)] transition-all cursor-pointer border bg-gradient-to-br",
                cat.color,
              )}>
                <CardContent className="p-5 space-y-3">
                  <div className="flex items-start justify-between">
                    <div className={cn("w-9 h-9 rounded-xl flex items-center justify-center", cat.iconBg)}>
                      <Icon className="w-4.5 h-4.5" />
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-500 transition-colors" />
                  </div>

                  <div>
                    <div className="text-[14px] font-bold text-slate-800">{cat.label}</div>
                    <div className="text-[11.5px] text-slate-500 mt-0.5 leading-relaxed">{cat.desc}</div>
                  </div>

                  {loading ? (
                    <Skeleton className="h-4 w-20" />
                  ) : s ? (
                    <div className="flex items-center gap-3 text-[11px] font-mono">
                      <span className="font-semibold text-slate-700">{s.total} items</span>
                      {s.active < s.total && (
                        <span className="text-slate-400">{s.active} active</span>
                      )}
                      {s.active === s.total && s.total > 0 && (
                        <span className="text-emerald-600">all active</span>
                      )}
                      {s.total === 0 && (
                        <span className="text-slate-400 italic">empty</span>
                      )}
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
