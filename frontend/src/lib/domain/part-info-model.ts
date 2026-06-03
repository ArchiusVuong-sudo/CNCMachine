/**
 * Part Information view-model — selects the identity fields the estimator wants
 * up front from the 2D drawing extraction, defaulting through the top-level
 * fields and the title_block sub-object.
 */
import type { VlmExtraction } from "@/lib/api/types";

/** PATCH column on a4_2d_extraction this field edits (item 3 inline editor). */
export type PartInfoKey = "part_number" | "revision" | "description" | "material" | "dimension_unit";

export interface PartInfoField {
  label: string;
  value?: string;
  /** Editable fields carry the a4_2d_extraction column they map to. */
  key?: PartInfoKey;
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
  const fields: PartInfoField[] = [
    { label: "Part Description", key: "description",     value: topLevel(vlm?.description) ?? tb(vlm, "description") ?? tb(vlm, "title") },
    { label: "Part Number",      key: "part_number",     value: topLevel(vlm?.part_number) ?? tb(vlm, "part_number") },
    { label: "Revision",         key: "revision",        value: topLevel(vlm?.revision) ?? tb(vlm, "revision") },
    { label: "Material",         key: "material",        value: topLevel(vlm?.material) },
    { label: "Dimension Unit",   key: "dimension_unit",  value: topLevel(vlm?.dimension_unit) ?? tb(vlm, "dimension_unit") },
  ];
  return fields;
}
