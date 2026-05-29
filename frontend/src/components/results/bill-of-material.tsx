"use client";

import { memo } from "react";
import { Table2, Plus, Trash2, Layers, Undo2 } from "lucide-react";
import type { Component } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { usd, minutes } from "@/lib/format";
import { ASSEMBLY_KEY, manualRowTotal, type FlatBomRow, type ManualBomRow } from "@/lib/domain/bom-model";
import { useBomTable } from "@/lib/hooks/useBomTable";
import { cn } from "@/lib/utils";

interface BillOfMaterialProps {
  components: Component[];
  assemblyName?: string;
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
  components, assemblyName, totalUsd, totalMin, selectedIndex, hoveredIndex, onSelect, className,
}: BillOfMaterialProps) {
  const {
    flat, totals, partsCount, hidden,
    addChild, setCell, removeManual, hideComponent, restoreHidden,
  } = useBomTable(components, totalMin, totalUsd);

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

      <div>
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col style={{ width: "48px" }} />   {/* LVL */}
            <col style={{ width: "56px" }} />   {/* QTY */}
            <col style={{ width: "190px" }} />  {/* Part Number */}
            <col style={{ width: "150px" }} />  {/* Description */}
            <col style={{ width: "120px" }} />  {/* Type */}
            <col style={{ width: "84px" }} />   {/* Material */}
            <col />                              {/* Machine — flex */}
            <col style={{ width: "84px" }} />   {/* Cycle */}
            <col style={{ width: "100px" }} />  {/* Material Cost */}
            <col style={{ width: "100px" }} />  {/* Process Cost */}
            <col style={{ width: "100px" }} />  {/* Total Cost */}
            <col style={{ width: "64px" }} />   {/* Actions */}
          </colgroup>
          <thead>
            <tr className="border-b border-border bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
              <Th className="text-left">Lvl</Th>
              <Th className="text-right">Qty</Th>
              <Th className="text-left">Part Number</Th>
              <Th className="text-left">Description</Th>
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
                  totals={totals}
                  selected={selectedIndex === null}
                  onSelect={() => onSelect(null)}
                  onAddChild={() => addChild(ASSEMBLY_KEY)}
                />
              ) : r.kind === "component" ? (
                <ComponentRow
                  key={r.row.key}
                  row={r.row}
                  level={r.level}
                  active={selectedIndex === r.row.componentIndex}
                  hovered={hoveredIndex === r.row.componentIndex}
                  onSelect={() => onSelect(r.row.componentIndex)}
                  onAddChild={() => addChild(r.row.key)}
                  onHide={() => hideComponent(r.row.key)}
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
  assemblyName, totals, selected, onSelect, onAddChild,
}: {
  assemblyName?: string;
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
      <Td className="text-right text-muted-foreground">—</Td>
      <Td className="text-left" colSpan={2} title={assemblyName || "Assembly"}>
        <span className="inline-flex min-w-0 items-center gap-1.5 font-semibold">
          <Layers className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{assemblyName || "Assembly"}</span>
        </span>
      </Td>
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
  row, level, active, hovered, onSelect, onAddChild, onHide,
}: {
  row: import("@/lib/domain/bom-model").BomComponentRow;
  level: number;
  active: boolean;
  hovered?: boolean;
  onSelect: () => void;
  onAddChild: () => void;
  onHide: () => void;
}) {
  return (
    <tr
      onClick={onSelect}
      className={cn(
        "cursor-pointer transition-colors",
        active ? "bg-primary/10" : hovered ? "bg-primary/5" : "hover:bg-muted/40",
      )}
    >
      <LevelCell level={level} />
      <Td className="text-right tabular-nums">{row.qty}</Td>
      <Td className={cn("text-left font-medium", active && "text-primary")} title={row.partNumber}>{row.partNumber}</Td>
      <Td className="text-left text-muted-foreground" title={row.description ?? undefined}>{row.description || "—"}</Td>
      <Td className="text-left">
        {row.partType
          ? <Badge variant="secondary" className="text-[10px] capitalize">{row.partType.replace(/_/g, " ")}</Badge>
          : <span className="text-muted-foreground">—</span>}
      </Td>
      <Td className="text-left" title={row.material ?? undefined}>{row.material ?? <span className="text-muted-foreground">—</span>}</Td>
      <Td className="text-left" title={row.machine ?? undefined}>{row.machine ?? <span className="text-muted-foreground">—</span>}</Td>
      <Td className="whitespace-nowrap text-right tabular-nums">
        {row.cycleMin > 0
          ? minutes(row.cycleMin)
          : <span className="text-muted-foreground" title={row.consolidated ? "Consolidated into assembly" : undefined}>—</span>}
      </Td>
      <Td className="whitespace-nowrap text-right tabular-nums">{usd(row.materialUsd)}</Td>
      <Td className="whitespace-nowrap text-right tabular-nums">{usd(row.processUsd)}</Td>
      <Td className="whitespace-nowrap text-right font-semibold tabular-nums">{usd(row.totalUsd)}</Td>
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
      <CellInput value={row.qty} onChange={(v) => onSetCell("qty", v)} align="right" w="w-14" type="number" />
      <CellInput value={row.partNumber} onChange={(v) => onSetCell("partNumber", v)} placeholder="Part number" w="w-36" />
      <CellInput value={row.description} onChange={(v) => onSetCell("description", v)} placeholder="Description" w="w-44" />
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
  return <th className={cn("truncate px-2 py-2 font-medium", className)}>{children}</th>;
}

/** Default cell — truncates overflowing text with an ellipsis. Numeric /
 *  short-content cells override with `whitespace-nowrap` to keep on one line
 *  without truncation; long-text cells get an explicit title for tooltip. */
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
      className={cn("truncate px-2 py-2 align-middle", className)}
    >
      {children}
    </td>
  );
}

function LevelCell({ level, muted }: { level: number; muted?: boolean }) {
  return (
    <td className={cn("whitespace-nowrap px-2 py-2 text-left align-middle", muted ? "text-muted-foreground" : "")}>
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
    <td className={cn("px-2 py-1.5", align === "right" ? "text-right" : "text-left")}>
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
    <td className="whitespace-nowrap px-2 py-1.5 text-right align-middle">
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
            className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-red-50 hover:text-red-600"
            title={removeTitle ?? "Remove row"}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </td>
  );
}
