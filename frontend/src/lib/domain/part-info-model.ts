/**
 * Part Information view-model — selects the identity fields the estimator wants
 * up front from the 2D drawing extraction, defaulting through the top-level
 * fields and the title_block sub-object.
 */
import type { VlmExtraction } from "@/lib/api/types";

export interface PartInfoField {
  label: string;
  value?: string;
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
 * The identity fields shown in the Part Information card. Surface Finish and
 * the drawn/checked/date/scale/sheet/company sub-block are intentionally
 * omitted per the 27 May review.
 */
export function buildPartInfoFields(vlm: VlmExtraction | null | undefined): PartInfoField[] {
  return [
    { label: "Part Description", value: topLevel(vlm?.description) ?? tb(vlm, "description") ?? tb(vlm, "title") },
    { label: "Part Number",      value: topLevel(vlm?.part_number) ?? tb(vlm, "part_number") },
    { label: "Revision",         value: topLevel(vlm?.revision) ?? tb(vlm, "revision") },
    { label: "Material",         value: topLevel(vlm?.material) },
    { label: "Units",            value: topLevel(vlm?.dimension_unit) ?? tb(vlm, "dimension_unit") },
  ];
}
