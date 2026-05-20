"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { BomItem, Component } from "@/lib/api/types";
import { ArrowRight, AlertCircle } from "lucide-react";

interface Props {
  bomItems:   BomItem[];
  components: Component[];
}

const METHOD_BADGE: Record<string, string> = {
  description: "border-emerald-300/60 bg-emerald-50 text-emerald-700",
  tengc:       "border-blue-300/60 bg-blue-50 text-blue-700",
  unknown:     "border-slate-300/60 bg-slate-50 text-slate-500",
};

const METHOD_LABEL: Record<string, string> = {
  description: "name match",
  tengc:       "TENGC code",
  unknown:     "unmatched",
};

export function BomMappingTable({ bomItems, components }: Props) {
  if (!bomItems?.length) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-slate-400 justify-center">
        <AlertCircle className="w-4 h-4 text-slate-300" />
        No BOM items extracted from 2D drawing
      </div>
    );
  }

  // Build lookup: bom_item_no → matching components
  const compsByBom: Record<number, Component[]> = {};
  for (const comp of (components ?? [])) {
    const k = comp.mapped_to_bom_item;
    if (k != null) {
      if (!compsByBom[k]) compsByBom[k] = [];
      compsByBom[k].push(comp);
    }
  }

  // Unmatched components (no BOM item)
  const unmappedComps = (components ?? []).filter((c) => c.mapped_to_bom_item == null);

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 px-3 py-1.5 bg-slate-50 rounded-lg text-[10px] font-semibold uppercase tracking-widest text-slate-400">
        <span>2D BOM Item</span>
        <span className="text-center">Match</span>
        <span>3D Component</span>
      </div>

      {bomItems.map((bom) => {
        const matched = compsByBom[bom.item_no] ?? [];
        const hasMatch = matched.length > 0;
        const method   = (matched[0]?.mapping_method as string | undefined) ?? "unknown";

        return (
          <div
            key={bom.item_no}
            className={cn(
              "grid grid-cols-[1fr_auto_1fr] items-stretch gap-2 rounded-xl border px-3 py-2.5 transition-colors",
              hasMatch
                ? "bg-white border-slate-200/60"
                : "bg-slate-50/80 border-slate-200/40 opacity-60",
            )}
          >
            {/* BOM cell */}
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="w-5 h-5 rounded-md bg-slate-800 text-white text-[10px] font-mono font-bold flex items-center justify-center shrink-0">
                  {bom.item_no}
                </span>
                <span className="text-[12px] font-medium text-slate-800 truncate">
                  {bom.description || bom.part_number || `Item ${bom.item_no}`}
                </span>
              </div>
              {bom.part_number && (
                <div className="text-[10px] font-mono text-slate-400 pl-7">{bom.part_number}</div>
              )}
              {bom.qty != null && bom.qty > 1 && (
                <div className="text-[10px] text-slate-400 pl-7">Qty: {bom.qty}</div>
              )}
              {bom.material && (
                <div className="text-[10px] text-slate-400 pl-7 truncate">{bom.material}</div>
              )}
            </div>

            {/* Arrow + badge */}
            <div className="flex flex-col items-center justify-center gap-1">
              {hasMatch ? (
                <>
                  <ArrowRight className="w-3.5 h-3.5 text-amber-500" />
                  <Badge
                    variant="outline"
                    className={cn("text-[9px] font-semibold px-1.5 py-0 border", METHOD_BADGE[method])}
                  >
                    {METHOD_LABEL[method]}
                  </Badge>
                </>
              ) : (
                <span className="text-[10px] text-slate-300 font-mono">—</span>
              )}
            </div>

            {/* Component cell */}
            <div className="space-y-1">
              {hasMatch ? (
                matched.map((comp) => (
                  <div key={comp.component_index} className="space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded bg-amber-100 text-amber-700 text-[9px] font-mono font-bold flex items-center justify-center shrink-0">
                        {comp.component_index}
                      </span>
                      <span className="text-[12px] font-medium text-slate-800 truncate">
                        {comp.name || `Component ${comp.component_index}`}
                      </span>
                    </div>
                    {comp.description && (
                      <div className="text-[10px] text-slate-400 pl-5.5 truncate">{comp.description}</div>
                    )}
                  </div>
                ))
              ) : (
                <div className="flex items-center gap-1.5 text-[11px] text-slate-400 italic">
                  <AlertCircle className="w-3 h-3 text-slate-300" />
                  No 3D match
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* Unmatched components section */}
      {unmappedComps.length > 0 && (
        <div className="pt-2 border-t border-slate-100 space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 px-1">
            3D-only (not in BOM)
          </div>
          {unmappedComps.map((comp) => (
            <div
              key={comp.component_index}
              className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-200/40 bg-slate-50/50"
            >
              <span className="w-5 h-5 rounded bg-slate-200 text-slate-600 text-[9px] font-mono font-bold flex items-center justify-center shrink-0">
                {comp.component_index}
              </span>
              <span className="text-[12px] text-slate-500 flex-1 truncate">
                {comp.name || `Component ${comp.component_index}`}
              </span>
              <span className="text-[10px] text-slate-400 italic">Not in BOM</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
