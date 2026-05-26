"use client";

import { FileText } from "lucide-react";
import type { VlmExtraction } from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface TitleBlockProps {
  vlm?: VlmExtraction | null;
  className?: string;
}

/** Read a value off the title_block sub-object defensively. */
function tb(vlm: VlmExtraction | null | undefined, key: string): string | undefined {
  const block = vlm?.title_block;
  if (!block || typeof block !== "object") return undefined;
  const v = (block as Record<string, unknown>)[key];
  return v == null || v === "" ? undefined : String(v);
}

function topLevel(v: unknown): string | undefined {
  return v == null || v === "" ? undefined : String(v);
}

/**
 * Title-block summary. The primary five fields the estimator wants up front —
 * Part Description, Part Number, Revision, Material, Units — sit in a prominent
 * grid; the rest of the title block (drawn/checked/date/scale/sheet/company)
 * follows underneath when present.
 */
export function TitleBlock({ vlm, className }: TitleBlockProps) {
  const primary: { label: string; value?: string }[] = [
    { label: "Part Description", value: topLevel(vlm?.description) ?? tb(vlm, "description") ?? tb(vlm, "title") },
    { label: "Part Number",      value: topLevel(vlm?.part_number) ?? tb(vlm, "part_number") },
    { label: "Revision",         value: topLevel(vlm?.revision) ?? tb(vlm, "revision") },
    { label: "Material",         value: topLevel(vlm?.material) },
    { label: "Units",            value: topLevel(vlm?.dimension_unit) ?? tb(vlm, "dimension_unit") },
    { label: "Surface Finish",   value: topLevel(vlm?.surface_finish) },
  ];

  const secondary: { label: string; value?: string }[] = [
    { label: "Drawn By",   value: tb(vlm, "drawn_by") },
    { label: "Checked By", value: tb(vlm, "checked_by") },
    { label: "Date",       value: tb(vlm, "date") },
    { label: "Scale",      value: tb(vlm, "scale") },
    { label: "Sheet",      value: tb(vlm, "sheet") },
    { label: "Company",    value: tb(vlm, "company") },
  ].filter((f) => f.value);

  return (
    <div className={cn("rounded-xl border border-border bg-card", className)}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <FileText className="h-4 w-4" />
        </div>
        <div>
          <h3 className="text-sm font-semibold leading-none">Title Block</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">Extracted from the 2D drawing</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-b-xl bg-border sm:grid-cols-3">
        {primary.map((f) => (
          <Field key={f.label} label={f.label} value={f.value} />
        ))}
      </div>

      {secondary.length > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border px-4 py-3 sm:grid-cols-3">
          {secondary.map((f) => (
            <div key={f.label} className="flex items-baseline justify-between gap-2 text-xs">
              <span className="text-muted-foreground">{f.label}</span>
              <span className="truncate font-medium">{f.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <div className="bg-card px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-sm font-semibold", !value && "font-normal text-muted-foreground/60")}>
        {value ?? "—"}
      </div>
    </div>
  );
}
