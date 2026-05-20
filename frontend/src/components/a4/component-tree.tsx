"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { Component } from "@/lib/api/types";
import {
  Drill,
  Layers,
  Circle,
  Shapes,
  Flame,
  Printer,
  Package,
  ChevronRight,
} from "lucide-react";

interface Props {
  components: Component[];
  selectedIndex?: number;
  onSelect?: (index: number) => void;
}

const PART_TYPE_META: Record<string, {
  label: string;
  color: string;
  icon: React.ComponentType<{ className?: string }>;
}> = {
  cnc_milling:        { label: "CNC Mill",     color: "border-amber-400/40 bg-amber-50 text-amber-700",   icon: Drill   },
  cnc_turning:        { label: "Lathe",        color: "border-blue-400/40 bg-blue-50 text-blue-700",      icon: Circle  },
  cnc_lathe:          { label: "Lathe",        color: "border-blue-400/40 bg-blue-50 text-blue-700",      icon: Circle  },
  cnc_lathe_milling:  { label: "Mill-Turn",    color: "border-sky-400/40 bg-sky-50 text-sky-700",         icon: Circle  },
  mill_turn:          { label: "Mill-Turn",    color: "border-sky-400/40 bg-sky-50 text-sky-700",         icon: Circle  },
  sheet_metal:        { label: "Sheet Metal",  color: "border-indigo-400/40 bg-indigo-50 text-indigo-700",icon: Layers  },
  tube_pipe:          { label: "Tube/Pipe",    color: "border-cyan-400/40 bg-cyan-50 text-cyan-700",      icon: Circle  },
  casting:            { label: "Casting",      color: "border-orange-400/40 bg-orange-50 text-orange-700",icon: Shapes  },
  weldment:           { label: "Weldment",     color: "border-red-400/40 bg-red-50 text-red-700",         icon: Flame   },
  additive:           { label: "3D Print",     color: "border-purple-400/40 bg-purple-50 text-purple-700",icon: Printer },
  hardware:           { label: "Hardware",     color: "border-slate-400/40 bg-slate-50 text-slate-700",   icon: Package },
};

function confidenceDot(conf: number) {
  if (conf >= 0.9) return "bg-emerald-400";
  if (conf >= 0.7) return "bg-amber-400";
  return "bg-red-400";
}

export function ComponentTree({ components, selectedIndex, onSelect }: Props) {
  if (!components?.length) {
    return (
      <div className="py-8 text-center text-sm text-slate-400 font-mono">
        No components detected
      </div>
    );
  }

  return (
    <div className="space-y-1.5" role="listbox" aria-label="Assembly components">
      {components.map((comp) => {
        const partType = comp.part_type ?? "cnc_milling";
        const meta   = PART_TYPE_META[partType] ?? PART_TYPE_META["cnc_milling"];
        const Icon   = meta.icon;
        const sel    = selectedIndex === comp.component_index;
        const hasBom = comp.mapped_to_bom_item != null;
        const conf   = comp.part_type_confidence ?? 0;

        return (
          <button
            key={comp.component_index}
            role="option"
            aria-selected={sel}
            onClick={() => onSelect?.(comp.component_index)}
            className={cn(
              "w-full text-left flex items-center gap-3 px-3.5 py-2.5 rounded-xl border transition-all group",
              sel
                ? "bg-amber-50 border-amber-300/70 shadow-[0_0_0_1px_theme(colors.amber.300/40)]"
                : "bg-white border-slate-200/60 hover:border-amber-200 hover:bg-amber-50/40",
            )}
          >
            {/* Index pill */}
            <span className={cn(
              "flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-mono font-bold",
              sel ? "bg-amber-500 text-white" : "bg-slate-100 text-slate-500",
            )}>
              {comp.component_index}
            </span>

            {/* Name + desc */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn(
                  "text-[12.5px] font-semibold truncate",
                  sel ? "text-amber-900" : "text-slate-800",
                )}>
                  {comp.name || `Component ${comp.component_index}`}
                </span>
                {/* Confidence dot */}
                <span
                  className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", confidenceDot(conf))}
                  title={`Classifier confidence: ${(conf * 100).toFixed(0)}%`}
                />
              </div>
              {comp.description && (
                <div className="text-[10.5px] text-slate-400 truncate">{comp.description}</div>
              )}
              {/* Bbox */}
              {comp.bbox && (
                <div className="text-[10px] font-mono text-slate-400 mt-0.5">
                  {comp.bbox.length_mm?.toFixed(1)}×{comp.bbox.width_mm?.toFixed(1)}×{comp.bbox.height_mm?.toFixed(1)} mm
                </div>
              )}
            </div>

            {/* Part type badge */}
            <Badge
              variant="outline"
              className={cn("text-[10px] font-semibold shrink-0 px-2 py-0.5 border", meta.color)}
            >
              <Icon className="w-2.5 h-2.5 mr-1 inline-block" />
              {meta.label}
            </Badge>

            {/* BOM mapping arrow */}
            {hasBom && (
              <span className="text-[10px] font-mono text-amber-600 bg-amber-100 rounded px-1.5 py-0.5 shrink-0 flex items-center gap-1">
                <ChevronRight className="w-2.5 h-2.5" />
                BOM #{comp.mapped_to_bom_item}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
