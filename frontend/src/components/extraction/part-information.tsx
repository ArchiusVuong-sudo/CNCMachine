"use client";

import { FileText, DollarSign, Boxes, StickyNote } from "lucide-react";
import type { VlmExtraction } from "@/lib/api/types";
import { usd } from "@/lib/format";
import { buildPartInfoFields } from "@/lib/domain/part-info-model";
import { drawingNotes } from "@/lib/domain/extraction-model";
import { cn } from "@/lib/utils";

interface PartInformationProps {
  vlm?: VlmExtraction | null;
  totalUsd?: number;
  totalUsdPerLot?: number;
  batchSize?: number;
  confidenceBandPct?: number | null;
  nComponents?: number;
  className?: string;
}

/**
 * Part Information card (formerly "Title Block"). Per the 28 May review it
 * shows the identity fields the estimator wants up front — Part Description,
 * Part Number, Revision, Material, Units — followed by the drawing Notes
 * (moved here from the extraction tabs). Total Cost + components count sit
 * in the footer.
 *
 * Presentation only — the field selection comes from `buildPartInfoFields`
 * and the notes from `drawingNotes`. Sized to fill its grid cell so it lines
 * up with the 3D / 2D viewer height.
 */
export function PartInformation({ vlm, totalUsd, totalUsdPerLot, batchSize, confidenceBandPct, nComponents, className }: PartInformationProps) {
  const fields = buildPartInfoFields(vlm);
  const notes = drawingNotes(vlm);
  const showLot = typeof totalUsdPerLot === "number" && typeof batchSize === "number" && batchSize > 1;
  const showConf = typeof confidenceBandPct === "number";

  return (
    <div className={cn("flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card", className)}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <FileText className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold leading-none">Part Information</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">Extracted from the 2D drawing</p>
        </div>
      </div>

      <div className="min-h-0 flex-1 divide-y divide-border overflow-auto">
        {fields.map((f) => (
          <div key={f.label} className="px-4 py-3">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{f.label}</div>
            <div className={cn("mt-1 text-sm font-semibold", !f.value && "font-normal text-muted-foreground/60")}>
              {f.value ?? "—"}
            </div>
          </div>
        ))}

        <div className="px-4 py-3">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <StickyNote className="h-3 w-3" />
            Notes
            {notes.length > 0 && (
              <span className="rounded bg-muted px-1.5 text-[10px] font-semibold tabular-nums text-muted-foreground/80">
                {notes.length}
              </span>
            )}
          </div>
          {notes.length === 0 ? (
            <div className="mt-1 text-sm font-normal text-muted-foreground/60">No drawing notes detected</div>
          ) : (
            <ol className="mt-1.5 space-y-1.5">
              {notes.map((n, i) => (
                <li key={i} className="flex gap-2 text-[13px] leading-snug">
                  <span className="select-none shrink-0 font-mono text-[11px] text-muted-foreground/70">{i + 1}.</span>
                  <span className="text-foreground/90">{n}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      {/* Total Cost + number of components */}
      <div className="grid grid-cols-2 gap-px border-t border-border bg-border">
        <Summary
          icon={<DollarSign className="h-3.5 w-3.5" />}
          label="Total Cost"
          value={usd(totalUsd)}
          accent
        />
        <Summary
          icon={<Boxes className="h-3.5 w-3.5" />}
          label="Components"
          value={nComponents != null ? String(nComponents) : "—"}
        />
      </div>

      {(showLot || showConf) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
          {showLot && (
            <span>Per lot (×{batchSize}): <span className="font-semibold tabular-nums text-foreground/80">{usd(totalUsdPerLot)}</span></span>
          )}
          {showConf && (
            <span>Confidence band: <span className="font-semibold tabular-nums text-foreground/80">±{confidenceBandPct}%</span></span>
          )}
        </div>
      )}
    </div>
  );
}

function Summary({ icon, label, value, accent }: { icon: React.ReactNode; label: string; value: string; accent?: boolean }) {
  return (
    <div className="bg-card px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className={cn(accent ? "text-primary" : "text-muted-foreground")}>{icon}</span>
        {label}
      </div>
      <div className={cn("mt-1 text-lg font-bold tabular-nums", accent && "text-primary")}>{value}</div>
    </div>
  );
}
