"use client";

/**
 * Headless Cycle Time / Cost Breakdown — resolves the selected component (or
 * the level-0 assembly aggregate), owns the editable model with reset/dirty
 * tracking, the cost/cycle view toggle, and submitting corrections to the
 * feedback endpoint. No JSX: the breakdown component binds to this and renders.
 */
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import type { Component } from "@/lib/api/types";
import { sendFeedback } from "@/lib/api/client";
import {
  buildComponentModel,
  buildAssemblyModel,
  deriveTotals,
  toNumericPayload,
  type EditModel,
  type EditRow,
  type CostView,
} from "@/lib/domain/cost-model";
import { componentTotalUsd, componentCycleMin } from "@/lib/domain/selectors";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface Args {
  analysisId: string | null;
  components: Component[];
  selectedIndex: number | null;
  totalUsd?: number;
  totalMin?: number;
}

export interface UseCostBreakdown {
  selected: Component | null;
  editable: boolean;
  model: EditModel;
  view: CostView;
  setView: (v: CostView) => void;
  editing: boolean;
  toggleEditing: () => void;
  /** editing AND a single component is selected (the assembly aggregate is read-only). */
  edit: boolean;
  dirty: boolean;
  submitting: boolean;
  totals: ReturnType<typeof deriveTotals>;
  headTotal: number;
  headCycle: number;
  setField: (key: keyof Omit<EditModel, "rows">, v: string) => void;
  setRow: (id: string, key: keyof EditRow, v: string) => void;
  reset: () => void;
  submit: () => Promise<void>;
}

export function useCostBreakdown({
  analysisId, components, selectedIndex, totalUsd, totalMin,
}: Args): UseCostBreakdown {
  const selected = selectedIndex == null ? null : components.find((c) => c.component_index === selectedIndex) ?? null;
  const editable = selected != null;

  const initial = useMemo(
    () => (selected ? buildComponentModel(selected) : buildAssemblyModel(components)),
    [selected, components],
  );

  const [model, setModel] = useState<EditModel>(initial);
  const [baseline, setBaseline] = useState<EditModel>(initial);
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [view, setView] = useState<CostView>("cost");

  // Re-seed when the selection (or its data) changes — effect-free: derive the
  // key and reset model/baseline during render when it shifts.
  const seedKey = useMemo(() => `${selectedIndex ?? "asm"}:${JSON.stringify(initial)}`, [selectedIndex, initial]);
  const [seed, setSeed] = useState(seedKey);
  if (seed !== seedKey) {
    setSeed(seedKey);
    setModel(initial);
    setBaseline(initial);
    setEditing(false);
  }

  const dirty = useMemo(() => JSON.stringify(model) !== JSON.stringify(baseline), [model, baseline]);
  const totals = useMemo(() => deriveTotals(model), [model]);

  const headTotal = selected
    ? componentTotalUsd(selected)
    : (typeof totalUsd === "number" ? totalUsd : totals.total);
  // Use the canonical per-component cycle (prefers the backend's component-level
  // cycle_time_min, which now includes legacy deburr+inspection time) so the
  // headline reconciles with the Bill of Material — which reads the same
  // selector. Falls back to the row-sum for routing components, where the two
  // are equal by construction.
  const headCycle = selected ? componentCycleMin(selected) : (typeof totalMin === "number" ? totalMin : totals.cycle);

  const setField = useCallback(
    (key: keyof Omit<EditModel, "rows">, v: string) => setModel((m) => ({ ...m, [key]: v })),
    [],
  );
  const setRow = useCallback(
    (id: string, key: keyof EditRow, v: string) =>
      setModel((m) => ({ ...m, rows: m.rows.map((r) => (r.id === id ? { ...r, [key]: v } : r)) })),
    [],
  );
  const reset = useCallback(() => setModel(baseline), [baseline]);
  const toggleEditing = useCallback(() => setEditing((e) => !e), []);

  const submit = useCallback(async () => {
    if (!analysisId || !selected) {
      toast.error("Select a component to submit corrections.");
      return;
    }
    setSubmitting(true);
    try {
      await sendFeedback({
        analysis_id: analysisId,
        kind: "cost_correction",
        payload: {
          component_index: selected.component_index,
          name: selected.name,
          part_type: selected.part_type,
          corrected: toNumericPayload(model),
          original: toNumericPayload(baseline),
        },
      } as any);
      setBaseline(model);
      setEditing(false);
      toast.success(`Corrections submitted for ${selected.name ?? `component ${selected.component_index}`}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit corrections");
    } finally {
      setSubmitting(false);
    }
  }, [analysisId, selected, model, baseline]);

  return {
    selected, editable, model, view, setView, editing, toggleEditing,
    edit: editing && editable, dirty, submitting, totals, headTotal, headCycle,
    setField, setRow, reset, submit,
  };
}
