"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FinalAnswer } from "@/lib/api/types";
import { useAnalysisStream } from "@/lib/hooks/useAnalysisStream";
import { getAnalysis } from "@/lib/api/client";
import { resignRunSource, resignStoragePaths } from "@/lib/run-sources";
import { RunsPanel } from "./runs-panel";
import { NewEstimateDialog } from "./new-estimate-dialog";
import { EmptyState } from "./chrome";
import { LiveRunView, HistoryRunView } from "./run-views";
import { EMPTY_HIST, type HistState } from "./types";

type View =
  | { kind: "empty" }
  | { kind: "live" }
  | { kind: "history"; id: string };

/**
 * Top-level estimate workspace: owns the run-selection state machine (empty /
 * live / history), the live SSE hook, and historical-run loading. Rendering is
 * delegated — `LiveRunView` / `HistoryRunView` render the chrome + results
 * layout; this file only orchestrates which view is on screen.
 */
export function Workspace() {
  const hook = useAnalysisStream();

  const [view, setView]           = useState<View>({ kind: "empty" });
  const [hist, setHist]           = useState<HistState>(EMPTY_HIST);
  const [collapsed, setCollapsed] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);

  // Refresh the runs list once a live run reaches a terminal state, so the
  // freshly-persisted run shows up in history.
  const lastStatus = useRef(hook.status);
  useEffect(() => {
    if (lastStatus.current !== hook.status && (hook.status === "done" || hook.status === "error")) {
      setRefreshSignal((n) => n + 1);
    }
    lastStatus.current = hook.status;
  }, [hook.status]);

  // Load a historical run (results + re-signed viewer sources).
  useEffect(() => {
    if (view.kind !== "history") return;
    let cancelled = false;
    setHist({ ...EMPTY_HIST, loading: true });
    (async () => {
      try {
        const [res, cached] = await Promise.all([
          getAnalysis(view.id),
          resignRunSource(view.id),
        ]);
        if (cancelled) return;
        const results = res as FinalAnswer;

        // Prefer this browser's localStorage-cached signing. When it misses
        // (run opened on a different machine / cleared cache), fall back to
        // the durable storage refs the server persisted in the envelope so
        // geometry still renders. resignStoragePaths warms the cache too.
        let sources = cached;
        const haveGeometry = !!(cached && (cached.stepUrl || cached.drawingUrl));
        if (!haveGeometry && results?.sources) {
          const fromServer = await resignStoragePaths(view.id, {
            bucket:      results.sources.bucket,
            stepPath:    results.sources.step_path,
            drawingPath: results.sources.drawing_path,
            fileName:    results.sources.file_name ?? results.file_name ?? null,
          });
          if (cancelled) return;
          if (fromServer) sources = fromServer;
        }
        setHist({ results, sources, loading: false, error: null });
      } catch (e) {
        if (cancelled) return;
        setHist({ results: null, sources: null, loading: false, error: e instanceof Error ? e.message : "Failed to load run" });
      }
    })();
    return () => { cancelled = true; };
  }, [view]);

  const handleRun = useCallback((file3d: File, file2d: File, batch: number, partType: string | null) => {
    setDialogOpen(false);
    setView({ kind: "live" });
    void hook.run(file3d, file2d, batch, partType);
  }, [hook]);

  const handleSelectRun = useCallback((id: string) => {
    if (id === hook.analysisId) setView({ kind: "live" });
    else setView({ kind: "history", id });
  }, [hook.analysisId]);

  const isLiveActive = hook.status !== "idle";
  const activeId =
    view.kind === "live" ? hook.analysisId :
    view.kind === "history" ? view.id : null;

  const liveRun = isLiveActive && hook.analysisId
    ? {
        id: hook.analysisId,
        label: hook.sources?.fileName ?? "New project",
        streaming: hook.isStreaming || hook.isLoading,
      }
    : null;

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background">
      <RunsPanel
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        activeId={activeId}
        onSelectRun={handleSelectRun}
        onNewEstimate={() => setDialogOpen(true)}
        liveRun={liveRun}
        refreshSignal={refreshSignal}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {view.kind === "empty" ? (
          <EmptyState onNewEstimate={() => setDialogOpen(true)} />
        ) : view.kind === "live" ? (
          <LiveRunView key={hook.analysisId ?? "live"} hook={hook} onNewEstimate={() => setDialogOpen(true)} />
        ) : (
          <HistoryRunView key={view.id} hist={hist} analysisId={view.id} onNewEstimate={() => setDialogOpen(true)} />
        )}
      </main>

      <NewEstimateDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onRun={handleRun}
        busy={hook.isLoading}
      />
    </div>
  );
}
