"use client";

import { memo, useCallback, useState } from "react";
import { toast } from "sonner";
import { Table2, Plus, Trash2, Layers, Undo2 } from "lucide-react";
import type { BomItem, Component } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { InlineEdit } from "@/components/ui/inline-edit";
import { usd, minutes } from "@/lib/format";
import { ASSEMBLY_KEY, manualRowTotal, type BomComponentRow, type FlatBomRow, type ManualBomRow } from "@/lib/domain/bom-model";
import { useBomTable } from "@/lib/hooks/useBomTable";
import { patchAnalysis } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** Overlay this session's not-yet-reloaded inline edits on top of a computed
 *  BoM row (the DB-persisted ui_overrides are already baked in by
 *  buildComponentRows; this layers the optimistic local edits). */
function withEdits(row: BomComponentRow, edits?: Record<string, string>): BomComponentRow {
  if (!edits || Object.keys(edits).length === 0) return row;
  const s = (v: string | undefined, fb: string) => (v != null && v !== "" ? v : fb);
  const n = (v: string | undefined, fb: number) => {
    if (v == null || v === "") return fb;
    const x = Number(v);
    return Number.isFinite(x) ? x : fb;
  };
  const materialUsd = n(edits.materialUsd, row.materialUsd);
  const processUsd = n(edits.processUsd, row.processUsd);
  return {
    ...row,
    partNumber:  s(edits.partNumber, row.partNumber),
    description: s(edits.description, row.description),
    qty:         n(edits.qty, row.qty),
    partType:    edits.partType != null ? (edits.partType || undefined) : row.partType,
    material:    edits.material != null ? (edits.material || undefined) : row.material,
    machine:     edits.machine != null ? (edits.machine || undefined) : row.machine,
    cycleMin:    n(edits.cycleMin, row.cycleMin),
    materialUsd,
    processUsd,
    totalUsd:    n(edits.totalUsd, materialUsd + processUsd),
  };
}

interface BillOfMaterialProps {
  components: Component[];
  /** Drawing BOM (vlm.bom_items) — surfaces the real part number + 2D
   *  description for each mapped component. */
  bomItems?: BomItem[];
  /** When present, component-row cells become double-click editable and
   *  persist to the DB (overwrites the saved run). */
  analysisId?: string | null;
  assemblyName?: string;
  /** Drawing-level part description — stands in for the sole machined part's
   *  Description cell when it has no 2D-BOM line of its own (item 13). */
  drawingDescription?: string;
  totalUsd?: number;
  totalMin?: number;
  /** Selected component_index, or null for the level-0 assembly row. */
  selectedIndex: number | null;
  /** "Soft" highlight from a 3D mesh click — renders a lighter row tint
   *  without changing the navigated selection. */
  hoveredIndex?: number | null;
  onSelect: (index: number | null) => void;
  className?: string;
}

const COLS = 13;

/**
 * Assembly Bill of Material.
 *
 * Per the 28 May review:
 *  - "Part Name" is split into Part Number + Description.
 *  - The synthetic TOP_ASSEMBLY level-1 row is filtered out (it duplicated the
 *    level-0 row — see `isTopAssemblyComponent`).
 *  - "Add row" is no longer a header button; every row exposes an in-row Add
 *    (creates a manual child at LVL+1) and Delete (locally hides costed rows,
 *    permanently removes manual rows).
 *
 * Presentation only — rows, totals, and the manual-row + hidden-key state
 * come from `useBomTable`.
 */
export function BillOfMaterial({
  components, bomItems, analysisId, assemblyName, drawingDescription, totalUsd, totalMin, selectedIndex, hoveredIndex, onSelect, className,
}: BillOfMaterialProps) {
  const {
    flat, totals, partsCount, hidden,
    addChild, setCell, removeManual, hideComponent, restoreHidden,
  } = useBomTable(components, totalMin, totalUsd, bomItems, drawingDescription);

  // Optimistic local overrides for component-row inline edits (item 14). Keyed
  // by component_index → field → value. Applied via withEdits() on render;
  // persisted to a4_components.ui_overrides so a reload reflects them.
  const editable = !!analysisId;
  const [compEdits, setCompEdits] = useState<Record<number, Record<string, string>>>({});
  const editComponentCell = useCallback((ci: number, key: string, value: string) => {
    setCompEdits((before) => {
      if (analysisId) {
        patchAnalysis(analysisId, { components: [{ component_index: ci, overrides: { [key]: value } }] })
          .catch(() => { setCompEdits(before); toast.error("Couldn't save edit"); });
      }
      return { ...before, [ci]: { ...before[ci], [key]: value } };
    });
  }, [analysisId]);

  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-card", className)}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Table2 className="h-4 w-4" />
        </div>
        <h3 className="text-sm font-semibold leading-none">Bill of Material</h3>
        {partsCount > 0 && (
          <Badge variant="secondary" className="text-[10px]">{partsCount} part{partsCount !== 1 ? "s" : ""}</Badge>
        )}
        {hidden.size > 0 && (
          <Button variant="ghost" size="sm" className="ml-auto h-7 gap-1.5 text-muted-foreground" onClick={restoreHidden}>
            <Undo2 className="h-3.5 w-3.5" /> Restore {hidden.size} hidden
          </Button>
        )}
      </div>

      {/* Horizontal scroll on narrow screens — the costing columns stay
         readable instead of being squished on a phone. */}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] table-fixed text-[13px]">
          {/* Column widths: LVL, QTY, Part Number, Description, Type, Material,
             Machine (flex), Cycle, Material Cost, Process Cost, Total, Actions.
             No inline comments between <col>s — the surrounding whitespace
             would become a text-node child of <colgroup> (hydration error). */}
          <colgroup>
            <col style={{ width: "48px" }} />
            <col style={{ width: "172px" }} />
            <col style={{ width: "148px" }} />
            <col style={{ width: "88px" }} />
            <col style={{ width: "100px" }} />
            <col style={{ width: "118px" }} />
            <col />
            <col style={{ width: "92px" }} />
            <col style={{ width: "96px" }} />
            <col style={{ width: "96px" }} />
            <col style={{ width: "96px" }} />
            <col style={{ width: "60px" }} />
          </colgroup>
          <thead>
            <tr className="border-b border-border bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
              <Th className="text-left">Lvl</Th>
              <Th className="text-left">Part Number</Th>
              <Th className="text-left">Description</Th>
              <Th className="text-right">Qty</Th>
              <Th className="text-left">Type</Th>
              <Th className="text-left">Material</Th>
              <Th className="text-left">Machine</Th>
              <Th className="text-right">Cycle</Th>
              <Th className="text-right">Mat Cost</Th>
              <Th className="text-right">Proc Cost</Th>
              <Th className="text-right">Total</Th>
              <Th className="text-right"> </Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {flat.map((r) =>
              r.kind === "assembly" ? (
                <AssemblyRow
                  key="asm"
                  assemblyName={assemblyName}
                  assemblyDescription={drawingDescription}
                  totals={totals}
                  selected={selectedIndex === null}
                  onSelect={() => onSelect(null)}
                  onAddChild={() => addChild(ASSEMBLY_KEY)}
                />
              ) : r.kind === "component" ? (
                <ComponentRow
                  key={r.row.key}
                  row={withEdits(r.row, compEdits[r.row.componentIndex])}
                  level={r.level}
                  active={selectedIndex === r.row.componentIndex}
                  hovered={hoveredIndex === r.row.componentIndex}
                  editable={editable}
                  onSelect={() => onSelect(r.row.componentIndex)}
                  onAddChild={() => addChild(r.row.key)}
                  onHide={() => hideComponent(r.row.key)}
                  onEdit={(key, value) => editComponentCell(r.row.componentIndex, key, value)}
                />
              ) : (
                <ManualRow
                  key={r.row.id}
                  row={r.row}
                  level={r.level}
                  onSetCell={(k, v) => setCell(r.row.id, k, v)}
                  onAddChild={() => addChild(r.row.id)}
                  onRemove={() => removeManual(r.row.id)}
                />
              )
            )}

            {flat.length === 1 && (
              <tr>
                <td colSpan={COLS} className="px-4 py-8 text-center text-sm text-muted-foreground">
                  No components in this estimate. Use the row Add buttons to enter parts manually.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------------- *
 * Row variants
 * ----------------------------------------------------------------------- */

const AssemblyRow = memo(function AssemblyRow({
  assemblyName, assemblyDescription, totals, selected, onSelect, onAddChild,
}: {
  assemblyName?: string;
  assemblyDescription?: string;
  totals: { material: number; process: number; cycle: number; total: number };
  selected: boolean;
  onSelect: () => void;
  onAddChild: () => void;
}) {
  return (
    <tr
      onClick={onSelect}
      className={cn(
        "cursor-pointer transition-colors",
        selected ? "bg-primary/10" : "hover:bg-muted/40",
      )}
    >
      <Td className="text-left font-semibold text-primary">0</Td>
      <Td className="text-left" title={assemblyName || "Assembly"}>
        <span className="flex min-w-0 items-start gap-1.5">
          <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="break-words">{assemblyName || "Assembly"}</span>
        </span>
      </Td>
      <Td className="text-left" title={assemblyDescription || undefined}>
        {assemblyDescription || <span className="text-muted-foreground">—</span>}
      </Td>
      <Td className="text-right text-muted-foreground">—</Td>
      <Td className="text-left"><Badge variant="info" className="text-[10px]">Assy</Badge></Td>
      <Td className="text-left text-muted-foreground">—</Td>
      <Td className="text-left text-muted-foreground">—</Td>
      <Td className="whitespace-nowrap text-right tabular-nums">{minutes(totals.cycle)}</Td>
      <Td className="whitespace-nowrap text-right tabular-nums">{usd(totals.material)}</Td>
      <Td className="whitespace-nowrap text-right tabular-nums">{usd(totals.process)}</Td>
      <Td className="whitespace-nowrap text-right font-semibold tabular-nums">{usd(totals.total)}</Td>
      <ActionsCell onAddChild={onAddChild} />
    </tr>
  );
});

const ComponentRow = memo(function ComponentRow({
  row, level, active, hovered, editable, onSelect, onAddChild, onHide, onEdit,
}: {
  row: BomComponentRow;
  level: number;
  active: boolean;
  hovered?: boolean;
  editable?: boolean;
  onSelect: () => void;
  onAddChild: () => void;
  onHide: () => void;
  onEdit: (key: string, value: string) => void;
}) {
  const dash = <span className="text-muted-foreground">—</span>;
  const eTxt = (key: string, val: string) => <InlineEdit value={val} onSave={(v) => onEdit(key, v)} />;
  const eNum = (key: string, val: number, display: React.ReactNode) => (
    <InlineEdit value={String(val)} type="number" align="right" display={display} onSave={(v) => onEdit(key, v)} />
  );
  const typeBadge = row.partType
    ? <Badge variant="secondary" className="text-[10px] capitalize">{row.partType.replace(/_/g, " ")}</Badge>
    : null;
  const cycleDisp = row.cycleMin > 0
    ? minutes(row.cycleMin)
    : <span className="text-muted-foreground" title={row.consolidated ? "Consolidated into assembly" : undefined}>—</span>;

  return (
    <tr
      onClick={onSelect}
      className={cn(
        "cursor-pointer transition-colors",
        active ? "bg-primary/10" : hovered ? "bg-primary/5" : "hover:bg-muted/40",
      )}
    >
      <LevelCell level={level} />
      <Td className={cn("text-left", active && "text-primary")} title={row.partNumber}>
        {editable ? eTxt("partNumber", row.partNumber) : (row.partNumber || dash)}
      </Td>
      <Td className="text-left" title={row.description ?? undefined}>
        {editable ? eTxt("description", row.description) : (row.description || dash)}
      </Td>
      <Td className="text-right tabular-nums">{editable ? eNum("qty", row.qty, row.qty) : row.qty}</Td>
      <Td className="text-left">
        {editable
          ? <InlineEdit value={row.partType ?? ""} onSave={(v) => onEdit("partType", v)} display={typeBadge ?? undefined} />
          : (typeBadge ?? dash)}
      </Td>
      <Td className="text-left" title={row.material ?? undefined}>
        {editable ? eTxt("material", row.material ?? "") : (row.material ?? dash)}
      </Td>
      <Td className="text-left" title={row.machine ?? undefined}>
        {editable ? eTxt("machine", row.machine ?? "") : (row.machine ?? dash)}
      </Td>
      <Td className="whitespace-nowrap text-right tabular-nums">
        {editable ? eNum("cycleMin", row.cycleMin, cycleDisp) : cycleDisp}
      </Td>
      <Td className="whitespace-nowrap text-right tabular-nums">
        {editable ? eNum("materialUsd", row.materialUsd, usd(row.materialUsd)) : usd(row.materialUsd)}
      </Td>
      <Td className="whitespace-nowrap text-right tabular-nums">
        {editable ? eNum("processUsd", row.processUsd, usd(row.processUsd)) : usd(row.processUsd)}
      </Td>
      <Td className="whitespace-nowrap text-right font-semibold tabular-nums">
        {editable ? eNum("totalUsd", row.totalUsd, usd(row.totalUsd)) : usd(row.totalUsd)}
      </Td>
      <ActionsCell
        onAddChild={onAddChild}
        onRemove={onHide}
        removeTitle="Hide row (does not change totals)"
      />
    </tr>
  );
});

const ManualRow = memo(function ManualRow({
  row, level, onSetCell, onAddChild, onRemove,
}: {
  row: ManualBomRow;
  level: number;
  onSetCell: (key: keyof ManualBomRow, v: string) => void;
  onAddChild: () => void;
  onRemove: () => void;
}) {
  return (
    <tr className="bg-amber-50/40">
      <LevelCell level={level} muted />
      <CellInput value={row.partNumber} onChange={(v) => onSetCell("partNumber", v)} placeholder="Part number" w="w-36" />
      <CellInput value={row.description} onChange={(v) => onSetCell("description", v)} placeholder="Description" w="w-44" />
      <CellInput value={row.qty} onChange={(v) => onSetCell("qty", v)} align="right" w="w-14" type="number" />
      <CellInput value={row.type} onChange={(v) => onSetCell("type", v)} placeholder="Type" w="w-24" />
      <CellInput value={row.material} onChange={(v) => onSetCell("material", v)} placeholder="Material" w="w-28" />
      <CellInput value={row.machine} onChange={(v) => onSetCell("machine", v)} placeholder="Machine" w="w-28" />
      <CellInput value={row.cycle} onChange={(v) => onSetCell("cycle", v)} align="right" w="w-20" type="number" />
      <CellInput value={row.materialCost} onChange={(v) => onSetCell("materialCost", v)} align="right" w="w-24" type="number" />
      <CellInput value={row.processCost} onChange={(v) => onSetCell("processCost", v)} align="right" w="w-24" type="number" />
      <Td className="text-right font-semibold tabular-nums">{usd(manualRowTotal(row))}</Td>
      <ActionsCell onAddChild={onAddChild} onRemove={onRemove} removeTitle="Remove row" />
    </tr>
  );
});

/* ----------------------------------------------------------------------- *
 * Cells
 * ----------------------------------------------------------------------- */

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return <th className={cn("px-2 py-2 align-bottom font-medium", className)}>{children}</th>;
}

/** Default cell — shows content in FULL (wrapped, never clipped) per the
 *  1 June review ("Content in all columns need to be fully displayed").
 *  `align-top` keeps every column's first line on the same baseline so a row
 *  with a long wrapped Material/Description stays visually aligned (the old
 *  `align-middle` floated the short cells in the vertical centre of a tall row,
 *  which is what read as "misaligned"). */
function Td({
  children, className, colSpan, title,
}: {
  children: React.ReactNode;
  className?: string;
  colSpan?: number;
  title?: string;
}) {
  return (
    <td
      colSpan={colSpan}
      title={title}
      className={cn("break-words px-2 py-2 align-top", className)}
    >
      {children}
    </td>
  );
}

function LevelCell({ level, muted }: { level: number; muted?: boolean }) {
  return (
    <td className={cn("whitespace-nowrap px-2 py-2 text-left align-top", muted ? "text-muted-foreground" : "")}>
      <span className="inline-flex items-center gap-1">
        {level > 1 && (
          <span aria-hidden className="text-muted-foreground/40" style={{ paddingLeft: `${(level - 1) * 10}px` }}>
            ↳
          </span>
        )}
        <span className={cn("tabular-nums", level === 0 && "font-semibold text-primary")}>{level}</span>
      </span>
    </td>
  );
}

function CellInput({
  value, onChange, placeholder, align = "left", type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  align?: "left" | "right";
  /** Deprecated — kept for the call sites that still pass it; the column
   *  width now comes from the table's <colgroup>. */
  w?: string;
  type?: "text" | "number";
}) {
  return (
    <td className={cn("px-2 py-2 align-top", align === "right" ? "text-right" : "text-left")}>
      <Input
        type={type}
        inputMode={type === "number" ? "decimal" : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        className={cn("h-7 w-full text-sm", align === "right" && "text-right tabular-nums")}
      />
    </td>
  );
}

function ActionsCell({
  onAddChild, onRemove, removeTitle,
}: {
  onAddChild?: () => void;
  onRemove?: () => void;
  removeTitle?: string;
}) {
  return (
    <td className="whitespace-nowrap px-2 py-2 text-right align-top">
      <div className="flex items-center justify-end gap-1">
        {onAddChild && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onAddChild(); }}
            className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary"
            title="Add child row"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRemove(); }}
            className="flex h-6 w-6 items-center justify-center rounded text-red-500 transition-colors hover:bg-red-50 hover:text-red-700"
            title={removeTitle ?? "Remove row"}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </td>
  );
}
