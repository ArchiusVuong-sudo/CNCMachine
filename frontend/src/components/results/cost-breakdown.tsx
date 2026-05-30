"use client";

import { Pencil, RotateCcw, Send, Loader2, Boxes, Package, Layers, Wrench } from "lucide-react";
import type { Component } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { usd, minutes, toNum } from "@/lib/format";
import { rowTotal, type CostView, type EditModel } from "@/lib/domain/cost-model";
import { useCostBreakdown } from "@/lib/hooks/useCostBreakdown";
import { cn } from "@/lib/utils";

interface CostBreakdownProps {
  analysisId: string | null;
  components: Component[];
  selectedIndex: number | null;
  assemblyName?: string;
  totalUsd?: number;
  totalMin?: number;
  className?: string;
}

/**
 * Cycle Time & Cost Breakdown for the row selected in the Bill of Material —
 * or, when nothing is selected, the level-0 assembly aggregate. The two
 * prototype tables (cost vs. cycle) are merged into one with a view toggle;
 * a Complexity column sits left of Cycle Time. Every column is editable for a
 * single component, and edits can be submitted back as corrections.
 *
 * Presentation only — the editable model, view toggle, and feedback submission
 * come from `useCostBreakdown`.
 */
export function CostBreakdown({
  analysisId, components, selectedIndex, assemblyName, totalUsd, totalMin, className,
}: CostBreakdownProps) {
  const {
    selected, editable, model, view, setView, editing, toggleEditing, edit,
    dirty, submitting, totals, headTotal, headCycle, setField, setRow, reset, submit,
  } = useCostBreakdown({ analysisId, components, selectedIndex, totalUsd, totalMin });

  const name = selected ? (selected.name ?? `Component ${selected.component_index}`) : (assemblyName || "Assembly");
  const typeLabel = selected ? (selected.part_type ?? "—") : "Assembly";
  const isHardware = (selected?.part_type ?? "").toLowerCase() === "hardware";
  const headComplexity = selected?.complexity != null ? String(selected.complexity) : undefined;

  return (
    <div className={cn("flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card", className)}>
      {/* Header */}
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          {selected ? (isHardware ? <Package className="h-4 w-4" /> : <Boxes className="h-4 w-4" />) : <Layers className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-semibold">{name}</span>
            <Badge variant={selected ? "secondary" : "info"} className="shrink-0 text-[10px] capitalize">
              {typeLabel.replace(/_/g, " ")}
            </Badge>
            {headComplexity && <Badge variant="warning" className="shrink-0 text-[10px]">{headComplexity}</Badge>}
            {dirty && <Badge variant="warning" className="shrink-0 text-[10px]">edited</Badge>}
          </div>
          {selected?.material && <div className="truncate text-[11px] text-muted-foreground">{selected.material}</div>}
        </div>
        <div className="text-right">
          <div className="text-sm font-bold tabular-nums">{usd(headTotal)}</div>
          <div className="text-[11px] tabular-nums text-muted-foreground">{minutes(headCycle)}</div>
        </div>
        {editable && (
          <Button
            variant={editing ? "secondary" : "outline"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={toggleEditing}
          >
            <Pencil className="h-3.5 w-3.5" />
            {editing ? "Done" : "Edit"}
          </Button>
        )}
      </div>

      {/* View toggle */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-muted/40 p-0.5">
          <ViewTab active={view === "cost"} onClick={() => setView("cost")} label="Cost" />
          <ViewTab active={view === "cycle"} onClick={() => setView("cycle")} label="Cycle Time" />
        </div>
      </div>

      {/* Table */}
      <div className="min-h-0 flex-1 overflow-auto">
        {model.rows.length > 0 ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Process</th>
                {view === "cycle" ? (
                  <>
                    <th className="px-2 py-2 text-left font-medium">Complexity</th>
                    <th className="px-3 py-2 text-right font-medium">Cycle (min)</th>
                  </>
                ) : (
                  <>
                    <th className="px-2 py-2 text-right font-medium">Labor</th>
                    <th className="px-2 py-2 text-right font-medium">Burden</th>
                    <th className="px-2 py-2 text-right font-medium">Tool</th>
                    <th className="px-3 py-2 text-right font-medium">Total</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {model.rows.map((r) => (
                <tr key={r.id} className="hover:bg-muted/30">
                  <td className="min-w-0 max-w-70 px-3 py-2 align-top">
                    {edit ? (
                      <Input value={r.process} onChange={(e) => setRow(r.id, "process", e.target.value)} className="h-7 w-full text-sm" />
                    ) : (
                      <>
                        {r.compTag && (
                          <div className="mb-0.5 truncate text-[11px] text-muted-foreground" title={r.compTag}>
                            {r.compTag}
                          </div>
                        )}
                        <div className="truncate text-sm font-medium capitalize" title={r.process}>
                          {r.process.replace(/_/g, " ")}
                        </div>
                        {(r.opCode || r.machine) && (
                          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                            {r.opCode && <span className="font-mono">{r.opCode}</span>}
                            {r.machine && (
                              <span className="inline-flex max-w-40 items-center gap-0.5" title={r.machine}>
                                <Wrench className="h-3 w-3 shrink-0" />
                                <span className="truncate">{r.machine}</span>
                              </span>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </td>

                  {view === "cycle" ? (
                    <>
                      <TextCell edit={edit} value={r.complexity} placeholder="—" onChange={(v) => setRow(r.id, "complexity", v)} align="left" />
                      <NumCell edit={edit} value={r.cycleMin} onChange={(v) => setRow(r.id, "cycleMin", v)} render={() => minutes(toNum(r.cycleMin))} />
                    </>
                  ) : (
                    <>
                      <NumCell edit={edit} value={r.laborUsd} onChange={(v) => setRow(r.id, "laborUsd", v)} render={() => usd(toNum(r.laborUsd))} />
                      <NumCell edit={edit} value={r.burdenUsd} onChange={(v) => setRow(r.id, "burdenUsd", v)} render={() => usd(toNum(r.burdenUsd))} />
                      <NumCell edit={edit} value={r.toolUsd} onChange={(v) => setRow(r.id, "toolUsd", v)} render={() => usd(toNum(r.toolUsd))} />
                      <td className="px-3 py-2 text-right font-semibold tabular-nums">{usd(rowTotal(r))}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="px-4 py-4 text-sm text-muted-foreground">
            {isHardware
              ? "Purchased hardware — no machining routing."
              : (selected?.planner ?? selected?.agentic)?.suppressed_by_consolidation_gate
                ? "Machining consolidated into the assembly total."
                : "No process routing for this component."}
          </div>
        )}

        {/* Component-level money lines */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-border px-4 py-3">
          <MoneyLine label="Material" value={model.materialUsd} editing={edit} onChange={(v) => setField("materialUsd", v)} />
          <MoneyLine label="Setup" value={model.setupUsd} editing={edit} onChange={(v) => setField("setupUsd", v)} />
          <MoneyLine label="Deburr" value={model.deburrUsd} editing={edit} onChange={(v) => setField("deburrUsd", v)} />
          <MoneyLine label="Inspection" value={model.inspectionUsd} editing={edit} onChange={(v) => setField("inspectionUsd", v)} />
        </div>
      </div>

      {/* Totals + actions */}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/20 px-4 py-3">
        <div className="flex items-center gap-5 text-sm">
          <span className="text-muted-foreground">Machining <span className="font-semibold text-foreground tabular-nums">{usd(totals.machining)}</span></span>
          <span className="text-muted-foreground">Cycle <span className="font-semibold text-foreground tabular-nums">{minutes(totals.cycle)}</span></span>
          <span className="text-muted-foreground">Total <span className="text-base font-bold text-foreground tabular-nums">{usd(totals.total)}</span></span>
        </div>
        {edit && (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="h-8 gap-1.5" onClick={reset} disabled={!dirty || submitting}>
              <RotateCcw className="h-3.5 w-3.5" /> Reset
            </Button>
            <Button size="sm" className="h-8 gap-1.5" onClick={submit} disabled={!dirty || submitting}>
              {submitting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              Submit corrections
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function ViewTab({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-medium transition-colors",
        active ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}

function NumCell({
  edit, value, onChange, render,
}: {
  edit: boolean;
  value: string;
  onChange: (v: string) => void;
  render: () => string;
}) {
  return (
    <td className="px-2 py-2 text-right">
      {edit ? (
        <Input
          type="number"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="ml-auto h-7 w-20 text-right text-sm tabular-nums"
        />
      ) : (
        <span className="tabular-nums">{render()}</span>
      )}
    </td>
  );
}

function TextCell({
  edit, value, onChange, placeholder, align = "left",
}: {
  edit: boolean;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  align?: "left" | "right";
}) {
  return (
    <td className={cn("px-2 py-2", align === "right" ? "text-right" : "text-left")}>
      {edit ? (
        <Input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className="h-7 w-24 text-sm" />
      ) : (
        <span className={cn(!value && "text-muted-foreground")}>{value || placeholder || "—"}</span>
      )}
    </td>
  );
}

function MoneyLine({
  label, value, editing, onChange,
}: {
  label: string;
  value: string;
  editing: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 py-0.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      {editing ? (
        <Input
          type="number"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-24 text-right text-sm tabular-nums"
        />
      ) : (
        <span className="font-medium tabular-nums">{usd(toNum(value))}</span>
      )}
    </div>
  );
}
