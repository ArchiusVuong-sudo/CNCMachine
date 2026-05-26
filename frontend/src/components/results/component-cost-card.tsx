"use client";

import { useMemo, useState } from "react";
import {
  Pencil, RotateCcw, Send, ChevronDown, Package, Loader2, Boxes, Wrench,
} from "lucide-react";
import type { Component, RoutingRow } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { usd, minutes, num, toNum } from "@/lib/format";
import { sendFeedback } from "@/lib/api/client";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface EditRow {
  id: string;
  process: string;
  opCode?: string;
  machine?: string;
  cycleMin: string;
  laborUsd: string;
  burdenUsd: string;
  toolUsd: string;
}

interface EditModel {
  materialUsd: string;
  setupUsd: string;
  deburrUsd: string;
  inspectionUsd: string;
  rows: EditRow[];
}

function rowsFromComponent(comp: Component): RoutingRow[] {
  return comp.manufacturing_processes ?? comp.processes ?? [];
}

function buildModel(comp: Component): EditModel {
  const cost = comp.cost ?? {};
  const rows = rowsFromComponent(comp).map((p, i): EditRow => ({
    id: `${comp.component_index}-${p.op_code ?? p.op_id ?? i}-${i}`,
    process: String(p.process_type ?? p.category ?? p.op_code ?? `Process ${i + 1}`),
    opCode: p.op_code,
    machine: p.machine_ref?.machine_name,
    cycleMin: num(p.cycle_time_min) || "0",
    laborUsd: num(p.labor_cost_usd, 4) || "0",
    burdenUsd: num(p.machine_cost_usd, 4) || "0",
    toolUsd: num((p as any).tool_cost_usd, 4) || "0",
  }));
  return {
    materialUsd: num(cost.raw_material_usd, 4) || "0",
    setupUsd: num(cost.setup_usd, 4) || "0",
    deburrUsd: num(cost.deburr_usd, 4) || "0",
    inspectionUsd: num(cost.inspection_usd, 4) || "0",
    rows,
  };
}

const rowTotal = (r: EditRow) => toNum(r.laborUsd) + toNum(r.burdenUsd) + toNum(r.toolUsd);

function deriveTotals(m: EditModel) {
  const machining = m.rows.reduce((acc, r) => acc + rowTotal(r), 0);
  const cycle = m.rows.reduce((acc, r) => acc + toNum(r.cycleMin), 0);
  const total = toNum(m.materialUsd) + toNum(m.setupUsd) + machining + toNum(m.deburrUsd) + toNum(m.inspectionUsd);
  return { machining, cycle, total };
}

function toNumericPayload(m: EditModel) {
  const { machining, cycle, total } = deriveTotals(m);
  return {
    raw_material_usd: toNum(m.materialUsd),
    setup_usd: toNum(m.setupUsd),
    deburr_usd: toNum(m.deburrUsd),
    inspection_usd: toNum(m.inspectionUsd),
    machining_total_usd: Number(machining.toFixed(4)),
    total_usd: Number(total.toFixed(4)),
    total_cycle_min: Number(cycle.toFixed(4)),
    processes: m.rows.map((r) => ({
      process_type: r.process,
      op_code: r.opCode,
      cycle_time_min: toNum(r.cycleMin),
      labor_cost_usd: toNum(r.laborUsd),
      machine_cost_usd: toNum(r.burdenUsd),
      tool_cost_usd: toNum(r.toolUsd),
      total_cost_usd: Number(rowTotal(r).toFixed(4)),
    })),
  };
}

interface ComponentCostCardProps {
  analysisId: string | null;
  component: Component;
  defaultOpen?: boolean;
}

export function ComponentCostCard({ analysisId, component, defaultOpen }: ComponentCostCardProps) {
  const initial = useMemo(() => buildModel(component), [component]);
  const [model, setModel] = useState<EditModel>(initial);
  const [original, setOriginal] = useState<EditModel>(initial);
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(defaultOpen ?? false);
  const [submitting, setSubmitting] = useState(false);

  const dirty = useMemo(() => JSON.stringify(model) !== JSON.stringify(original), [model, original]);
  const totals = useMemo(() => deriveTotals(model), [model]);

  const partType = component.part_type ?? "—";
  const isHardware = partType.toLowerCase() === "hardware";

  const setField = (key: keyof Omit<EditModel, "rows">, v: string) =>
    setModel((m) => ({ ...m, [key]: v }));
  const setRow = (id: string, key: keyof EditRow, v: string) =>
    setModel((m) => ({ ...m, rows: m.rows.map((r) => (r.id === id ? { ...r, [key]: v } : r)) }));

  const reset = () => setModel(original);

  const submit = async () => {
    if (!analysisId) {
      toast.error("No analysis id — run an estimate first.");
      return;
    }
    setSubmitting(true);
    try {
      await sendFeedback({
        analysis_id: analysisId,
        kind: "cost_correction",
        payload: {
          component_index: component.component_index,
          name: component.name,
          part_type: component.part_type,
          corrected: toNumericPayload(model),
          original: toNumericPayload(original),
        },
      } as any);
      setOriginal(model); // corrections become the new baseline
      setEditing(false);
      toast.success(`Corrections submitted for ${component.name ?? `component ${component.component_index}`}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit corrections");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <CollapsibleTrigger asChild>
          <button className="flex flex-1 items-center gap-3 text-left">
            <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">
              {isHardware ? <Package className="h-4 w-4" /> : <Boxes className="h-4 w-4" />}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-semibold">{component.name ?? `Component ${component.component_index}`}</span>
                <Badge variant="secondary" className="shrink-0 text-[10px] capitalize">{partType.replace(/_/g, " ")}</Badge>
                {dirty && <Badge variant="warning" className="shrink-0 text-[10px]">edited</Badge>}
              </div>
              {component.material && <div className="truncate text-[11px] text-muted-foreground">{component.material}</div>}
            </div>
          </button>
        </CollapsibleTrigger>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-sm font-bold tabular-nums">{usd(totals.total)}</div>
            <div className="text-[11px] tabular-nums text-muted-foreground">{minutes(totals.cycle)}</div>
          </div>
          <Button
            variant={editing ? "secondary" : "outline"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={() => { setEditing((e) => !e); setOpen(true); }}
          >
            <Pencil className="h-3.5 w-3.5" />
            {editing ? "Done" : "Edit"}
          </Button>
        </div>
      </div>

      <CollapsibleContent>
        <div className="border-t border-border">
          {/* Process breakdown */}
          {model.rows.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30 text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="px-4 py-2 text-left font-medium">Process</th>
                    <th className="px-3 py-2 text-right font-medium">Cycle (min)</th>
                    <th className="px-3 py-2 text-right font-medium">Labor</th>
                    <th className="px-3 py-2 text-right font-medium">Burden</th>
                    <th className="px-3 py-2 text-right font-medium">Tool</th>
                    <th className="px-4 py-2 text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {model.rows.map((r) => (
                    <tr key={r.id} className="hover:bg-muted/30">
                      <td className="px-4 py-2">
                        <div className="font-medium capitalize">{r.process.replace(/_/g, " ")}</div>
                        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                          {r.opCode && <span className="font-mono">{r.opCode}</span>}
                          {r.machine && <span className="inline-flex items-center gap-0.5"><Wrench className="h-3 w-3" />{r.machine}</span>}
                        </div>
                      </td>
                      <NumTd editing={editing} value={r.cycleMin} onChange={(v) => setRow(r.id, "cycleMin", v)} render={() => minutes(toNum(r.cycleMin))} />
                      <NumTd editing={editing} value={r.laborUsd} onChange={(v) => setRow(r.id, "laborUsd", v)} render={() => usd(toNum(r.laborUsd))} />
                      <NumTd editing={editing} value={r.burdenUsd} onChange={(v) => setRow(r.id, "burdenUsd", v)} render={() => usd(toNum(r.burdenUsd))} />
                      <NumTd editing={editing} value={r.toolUsd} onChange={(v) => setRow(r.id, "toolUsd", v)} render={() => usd(toNum(r.toolUsd))} />
                      <td className="px-4 py-2 text-right font-semibold tabular-nums">{usd(rowTotal(r))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-4 py-3 text-sm text-muted-foreground">
              {isHardware ? "Purchased hardware — no machining routing." : "No process routing for this component."}
            </div>
          )}

          {/* Component-level lines */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-border px-4 py-3 sm:grid-cols-4">
            <MoneyLine label="Material" value={model.materialUsd} editing={editing} onChange={(v) => setField("materialUsd", v)} />
            <MoneyLine label="Setup" value={model.setupUsd} editing={editing} onChange={(v) => setField("setupUsd", v)} />
            <MoneyLine label="Deburr" value={model.deburrUsd} editing={editing} onChange={(v) => setField("deburrUsd", v)} />
            <MoneyLine label="Inspection" value={model.inspectionUsd} editing={editing} onChange={(v) => setField("inspectionUsd", v)} />
          </div>

          {/* Totals + actions */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border bg-muted/20 px-4 py-3">
            <div className="flex items-center gap-6 text-sm">
              <span className="text-muted-foreground">Machining <span className="font-semibold text-foreground tabular-nums">{usd(totals.machining)}</span></span>
              <span className="text-muted-foreground">Cycle <span className="font-semibold text-foreground tabular-nums">{minutes(totals.cycle)}</span></span>
              <span className="text-muted-foreground">Total <span className="text-base font-bold text-foreground tabular-nums">{usd(totals.total)}</span></span>
            </div>
            {editing && (
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
      </CollapsibleContent>
    </Collapsible>
  );
}

/** Editable numeric table cell (right-aligned). */
function NumTd({
  editing, value, onChange, render,
}: {
  editing: boolean;
  value: string;
  onChange: (v: string) => void;
  render: () => string;
}) {
  return (
    <td className="px-3 py-2 text-right">
      {editing ? (
        <Input
          type="number"
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-24 ml-auto text-right text-sm tabular-nums"
        />
      ) : (
        <span className="tabular-nums">{render()}</span>
      )}
    </td>
  );
}

/** Editable money line in the component-level grid. */
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
