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

/** Human-readable label for the drawing-level part_category enum. */
function prettyCategory(v: unknown): string | undefined {
  if (v == null || v === "") return undefined;
  const key = String(v).toLowerCase();
  const map: Record<string, string> = {
    weldment: "Weldment",
    assembly_bolted: "Bolted Assembly",
    assembly_riveted: "Riveted Assembly",
    assembly_bonded: "Bonded Assembly",
    assembly: "Assembly",
    sheet_metal: "Sheet Metal",
    cnc_milling: "CNC Milling",
    cnc_lathe: "CNC Lathe",
    cnc_lathe_milling: "CNC Turn-Mill",
    hardware: "Hardware",
  };
  return map[key] ?? String(v).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * The identity fields shown in the Part Information card. Surface Finish and
 * the drawn/checked/date/scale/sheet/company sub-block are intentionally
 * omitted per the 27 May review.
 */
export function buildPartInfoFields(vlm: VlmExtraction | null | undefined): PartInfoField[] {
  const fields: PartInfoField[] = [
    { label: "Part Description", value: topLevel(vlm?.description) ?? tb(vlm, "description") ?? tb(vlm, "title") },
    { label: "Part Number",      value: topLevel(vlm?.part_number) ?? tb(vlm, "part_number") },
    { label: "Revision",         value: topLevel(vlm?.revision) ?? tb(vlm, "revision") },
    { label: "Material",         value: topLevel(vlm?.material) },
    { label: "Units",            value: topLevel(vlm?.dimension_unit) ?? tb(vlm, "dimension_unit") },
  ];
  // Part Category is shown only when the pipeline classified one (weldment /
  // assembly / sheet_metal / …) so single-part drawings don't get a blank row.
  const category = prettyCategory(vlm?.part_category);
  if (category) fields.push({ label: "Part Category", value: category });
  return fields;
}
