"use client";

/**
 * Headless Bill of Material table — owns the user-added (manual) rows, the
 * per-row hidden set, and exposes the costed component rows + reconciled
 * totals from the domain layer. The BOM component binds to this and renders.
 *
 * Per the 28 May review the table is hierarchical: every row exposes Add
 * (creates a manual child at LVL+1) and Delete (locally hides). Costed-
 * component Delete is a visibility toggle and never mutates totals; manual
 * rows are removed permanently. Children of a hidden row are skipped along
 * with their parent.
 */
import { useCallback, useMemo, useState } from "react";
import type { BomItem, Component } from "@/lib/api/types";
import {
  ASSEMBLY_KEY,
  buildComponentRows,
  aggregateBom,
  emptyManualRow,
  flattenBom,
  isTopAssemblyComponent,
  type BomComponentRow,
  type ManualBomRow,
  type BomTotals,
  type FlatBomRow,
} from "@/lib/domain/bom-model";

export interface UseBomTable {
  /** Costed component rows (already filtered to drop the synthetic TOP_ASSEMBLY). */
  components: BomComponentRow[];
  manual: ManualBomRow[];
  /** Rows the user has locally hidden via Delete. */
  hidden: Set<string>;
  /** Display-ready, DFS-ordered flat list. */
  flat: FlatBomRow[];
  totals: BomTotals;
  partsCount: number;
  /** Add a manual child row beneath the row identified by parentKey. */
  addChild: (parentKey: string) => void;
  setCell: (id: string, key: keyof ManualBomRow, v: string) => void;
  /** Permanently remove a manual row (and its descendants). */
  removeManual: (id: string) => void;
  /** Locally hide a costed-component row (does NOT mutate cost totals). */
  hideComponent: (key: string) => void;
  /** Reveal all locally-hidden rows. */
  restoreHidden: () => void;
}

export function useBomTable(components: Component[], totalMin?: number, totalUsd?: number, bomItems: BomItem[] = [], drawingDescription = ""): UseBomTable {
  const [manual, setManual] = useState<ManualBomRow[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());

  const rows = useMemo(() => buildComponentRows(components, bomItems, drawingDescription), [components, bomItems, drawingDescription]);
  const totals = useMemo(() => aggregateBom(components, totalMin, totalUsd), [components, totalMin, totalUsd]);
  const flat = useMemo(() => flattenBom(rows, manual, hidden), [rows, manual, hidden]);
  const partsCount = useMemo(
    () => components.filter((c) => !isTopAssemblyComponent(c)).length,
    [components],
  );

  const addChild = useCallback(
    (parentKey: string) => setManual((m) => [...m, emptyManualRow(parentKey)]),
    [],
  );
  const setCell = useCallback(
    (id: string, key: keyof ManualBomRow, v: string) =>
      setManual((m) => m.map((r) => (r.id === id ? { ...r, [key]: v } : r))),
    [],
  );
  // Removing a manual row also removes its manual descendants — otherwise they'd
  // be orphaned (their parentKey points to a row that no longer exists).
  const removeManual = useCallback((id: string) => {
    setManual((m) => {
      const toRemove = new Set<string>([id]);
      let grew = true;
      while (grew) {
        grew = false;
        for (const r of m) {
          if (!toRemove.has(r.id) && toRemove.has(r.parentKey)) {
            toRemove.add(r.id);
            grew = true;
          }
        }
      }
      return m.filter((r) => !toRemove.has(r.id));
    });
  }, []);
  const hideComponent = useCallback(
    (key: string) =>
      setHidden((h) => {
        if (h.has(key)) return h;
        const next = new Set(h);
        next.add(key);
        return next;
      }),
    [],
  );
  const restoreHidden = useCallback(() => setHidden(new Set()), []);

  return {
    components: rows,
    manual,
    hidden,
    flat,
    totals,
    partsCount,
    addChild,
    setCell,
    removeManual,
    hideComponent,
    restoreHidden,
  };
}

export { ASSEMBLY_KEY };
