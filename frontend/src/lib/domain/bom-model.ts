/**
 * Bill of Material view-model — the presentation-ready rows and totals the BOM
 * table renders, derived from the same per-component selectors the Cost
 * Breakdown uses so the two always reconcile.
 *
 * Per the 28 May review the BOM table is hierarchical: every row has an Add
 * button that creates a child row at LVL+1, and a Delete button that hides it
 * locally. Manual rows can be edited freely and deleted permanently; costed
 * component rows can be hidden (Delete is a local visibility toggle that does
 * NOT mutate cost totals — the underlying analysis is the source of truth).
 *
 * Pure: the manual-row + hidden-key React state machine lives in `useBomTable`;
 * these are just the data shapes and the builders/reducers behind them.
 */
import type { BomItem, Component } from "@/lib/api/types";
import { toNum } from "@/lib/format";
import {
  componentMachine,
  componentCycleMin,
  componentMaterialUsd,
  componentTotalUsd,
} from "./selectors";

/** Key for the synthetic level-0 assembly row that's always rendered first. */
export const ASSEMBLY_KEY = "asm";

/** A level-1 component row, ready to render. */
export interface BomComponentRow {
  key: string;            // unique key used as parent identity for manual children
  componentIndex: number;
  qty: number;
  partNumber: string;
  description: string;
  partType?: string;
  material?: string;
  machine?: string;
  cycleMin: number;
  /** True when the planner consolidated this component's machining into
   *  the assembly owner — its cycle/cost is real but lives on the parent
   *  row, so this row should render "—" for cycle/process to avoid the
   *  "looks like a zero" reading. */
  consolidated?: boolean;
  materialUsd: number;
  processUsd: number;
  totalUsd: number;
}

/** A user-added BOM line — free-form, editable, not tied to a STEP component. */
export interface ManualBomRow {
  id: string;
  parentKey: string;      // ASSEMBLY_KEY | component key | another manual row id
  qty: string;
  partNumber: string;
  description: string;
  type: string;
  material: string;
  machine: string;
  cycle: string;
  materialCost: string;
  processCost: string;
}

export interface BomTotals {
  material: number;
  process: number;
  cycle: number;
  total: number;
}

/**
 * Some analyses include a synthetic "TOP_ASSEMBLY" component that carries the
 * assembly-level operations (welding, deburring, packaging, etc.). It's a
 * sibling of the actual level-1 child components, but renders as a duplicate
 * of the level-0 row in the BOM table — the 28 May review flagged it as
 * "not valid". We skip it from the per-component BOM rendering; its cost is
 * still summed into the level-0 totals through `aggregateBom`.
 */
export function isTopAssemblyComponent(c: Component): boolean {
  const pt = (c.part_type ?? "").toLowerCase();
  const name = (c.name ?? "").toUpperCase();
  return pt === "assembly_top" || pt === "top_assembly" || name === "TOP_ASSEMBLY";
}

/**
 * Index the drawing BOM by `item_no` (the 1-based key `mapped_to_bom_item`
 * references). The 2D extractor occasionally emits duplicate item_no rows — a
 * noise row carrying no part number alongside the real row — so when item_no
 * collides we keep the entry that actually has a part number / description.
 */
function indexBomByItemNo(bomItems: BomItem[]): Map<number, BomItem> {
  const byItemNo = new Map<number, BomItem>();
  for (const b of bomItems) {
    // item_no arrives as a string from the DB/JSON while mapped_to_bom_item is
    // a number — coerce both to Number or the Map lookup silently misses.
    const itemNo = Number(b?.item_no);
    if (!Number.isFinite(itemNo)) continue;
    const cur = byItemNo.get(itemNo);
    const richer =
      !cur ||
      (!cur.part_number && !!b.part_number) ||
      (!(cur.description ?? "").trim() && !!(b.description ?? "").trim());
    if (richer) byItemNo.set(itemNo, b);
  }
  return byItemNo;
}

/** Build the level-1 component rows from the costed components. `bomItems` is
 *  the drawing BOM (vlm.bom_items) used to surface the real part number +
 *  description for each mapped component. */
export function buildComponentRows(
  components: Component[],
  bomItems: BomItem[] = [],
  drawingDescription = "",
): BomComponentRow[] {
  const byItemNo = indexBomByItemNo(bomItems);
  const visible = components.filter((c) => !isTopAssemblyComponent(c));
  // The drawing's part description stands in only for the ONE main machined
  // part of a single-part drawing (1 June review item 13 — descriptions come
  // from the 2D drawing). With several machined parts each carries its own
  // 2D-BOM description, so we don't repeat the assembly description across them.
  const isHardwareComp = (c: Component) =>
    (c.part_type ?? "").toLowerCase() === "hardware" ||
    ((c as { component_role?: string }).component_role ?? "").toLowerCase() === "hardware";
  const machined = visible.filter((c) => !isHardwareComp(c));
  const soleMachinedIdx = machined.length === 1 ? machined[0].component_index : null;
  return visible
    .map((c) => {
      const material = componentMaterialUsd(c);
      const total = componentTotalUsd(c);
      const bomItem = c.mapped_to_bom_item != null ? byItemNo.get(Number(c.mapped_to_bom_item)) : undefined;
      // The real drawing part number, or blank — never the STEP `TC…` code,
      // which is an internal identifier, not a purchasable part number.
      const partNumber = (bomItem?.part_number ?? "").trim();
      // Description comes from the 2D drawing BOM; fall back to the component's
      // own description (rare) so the column isn't needlessly empty.
      const description =
        (bomItem?.description ?? "").trim() ||
        (c.description ?? "").trim() ||
        (c.component_index === soleMachinedIdx ? (drawingDescription ?? "").trim() : "");
      const planner = c.planner ?? c.agentic;
      // User display corrections from the BoM inline editor (persisted to
      // a4_components.ui_overrides). Applied on top of the computed values so a
      // reloaded run shows the saved edits. Numeric fields coerce; blank/absent
      // override falls back to the computed value.
      const ov = (c.ui_overrides && typeof c.ui_overrides === "object"
        ? c.ui_overrides : {}) as Record<string, string | undefined>;
      const oStr = (v: string | undefined, fallback: string) => (v != null && v !== "" ? v : fallback);
      const oNum = (v: string | undefined, fallback: number) => {
        if (v == null || v === "") return fallback;
        const n = Number(v);
        return Number.isFinite(n) ? n : fallback;
      };
      const materialUsd = oNum(ov.materialUsd, material);
      const processUsd = oNum(ov.processUsd, total - material);
      return {
        key: String(c.id ?? c.component_index),
        componentIndex: c.component_index,
        qty: oNum(ov.qty, c.instance_count ?? 1),
        partNumber: oStr(ov.partNumber, partNumber),
        description: oStr(ov.description, description),
        partType: oStr(ov.partType, c.part_type ?? "") || undefined,
        material: oStr(ov.material, c.material ?? "") || undefined,
        machine: oStr(ov.machine, componentMachine(c) ?? "") || undefined,
        cycleMin: oNum(ov.cycleMin, componentCycleMin(c)),
        consolidated: !!planner?.suppressed_by_consolidation_gate,
        // Process = everything that isn't raw material, so Material + Process =
        // Total always reconciles against the authoritative per-component total.
        materialUsd,
        processUsd,
        totalUsd: oNum(ov.totalUsd, materialUsd + processUsd),
      };
    });
}

/** Aggregate the level-0 assembly row from the components (or override totals). */
export function aggregateBom(
  components: Component[],
  totalMin?: number,
  totalUsd?: number,
): BomTotals {
  // Sum over ALL components (including TOP_ASSEMBLY) so the level-0 headline
  // reconciles with the authoritative cost block from the orchestrator.
  const material = components.reduce((a, c) => a + componentMaterialUsd(c), 0);
  const cycle = typeof totalMin === "number" ? totalMin : components.reduce((a, c) => a + componentCycleMin(c), 0);
  const total = typeof totalUsd === "number" ? totalUsd : components.reduce((a, c) => a + componentTotalUsd(c), 0);
  return { material, process: total - material, cycle, total };
}

export function emptyManualRow(parentKey: string = ASSEMBLY_KEY): ManualBomRow {
  // Random suffix so multiple Adds in the same ms still produce unique ids.
  const id = `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return {
    id, parentKey,
    qty: "1", partNumber: "", description: "", type: "",
    material: "", machine: "", cycle: "", materialCost: "", processCost: "",
  };
}

export const manualRowTotal = (r: ManualBomRow): number => toNum(r.materialCost) + toNum(r.processCost);

/* ------------------------------------------------------------------------- *
 * Tree walk — the BOM table renders rows in DFS order so a manual child
 * row appears immediately under its parent, regardless of insertion order.
 * ------------------------------------------------------------------------- */

export type FlatBomRow =
  | { kind: "assembly"; level: 0; key: typeof ASSEMBLY_KEY }
  | { kind: "component"; level: number; row: BomComponentRow }
  | { kind: "manual"; level: number; row: ManualBomRow };

/**
 * Flatten the BOM into the display order: assembly → for each level-1 row
 * (components in their original order, then any manual rows with parentKey
 * "asm"), then recursively for each row's manual children. Hidden rows are
 * skipped, along with all their descendants.
 */
export function flattenBom(
  components: BomComponentRow[],
  manual: ManualBomRow[],
  hidden: Set<string>,
): FlatBomRow[] {
  const out: FlatBomRow[] = [];
  if (hidden.has(ASSEMBLY_KEY)) return out; // shouldn't happen; level-0 isn't deletable
  out.push({ kind: "assembly", level: 0, key: ASSEMBLY_KEY });

  // Manual rows indexed by parentKey for fast lookup.
  const manualByParent = new Map<string, ManualBomRow[]>();
  for (const m of manual) {
    const list = manualByParent.get(m.parentKey) ?? [];
    list.push(m);
    manualByParent.set(m.parentKey, list);
  }

  const visitManualChildren = (parentKey: string, level: number) => {
    for (const m of manualByParent.get(parentKey) ?? []) {
      if (hidden.has(m.id)) continue;
      out.push({ kind: "manual", level, row: m });
      visitManualChildren(m.id, level + 1);
    }
  };

  for (const c of components) {
    if (hidden.has(c.key)) continue;
    out.push({ kind: "component", level: 1, row: c });
    visitManualChildren(c.key, 2);
  }
  // Manual rows that are direct children of the assembly are level-1 too.
  visitManualChildren(ASSEMBLY_KEY, 1);

  return out;
}
