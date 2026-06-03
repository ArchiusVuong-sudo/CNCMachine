"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { FinalAnswer } from "@/lib/api/types";
import { useAnalysisStreamContext } from "@/lib/hooks/analysis-stream-context";
import { getAnalysis } from "@/lib/api/client";
import { resignRunSource, resignStoragePaths } from "@/lib/run-sources";
import { Menu } from "lucide-react";
import { RunsPanel } from "./runs-panel";
import { BrandMark } from "@/components/layout/brand-mark";
import { NewEstimateDialog } from "./new-estimate-dialog";
import { EmptyState } from "./chrome";
import { LiveRunView, HistoryRunView } from "./run-views";
import { EMPTY_HIST, type HistState } from "./types";

type View =
  | { kind: "empty" }
  | { kind: "live" }
  | { kind: "history"; id: string };

/**
 * Top-level estimate workspace. The view is URL-driven:
 *   - `/`                → dashboard (empty) or the in-flight live run.
 *   - `/save-run/<id>`   → a saved run (the `savedRunId` prop, from the route).
 * Selecting a saved run navigates to `/save-run/<id>`; the CoFab logo links to
 * `/`. The live SSE hook + historical-run loading live here; rendering is
 * delegated to `LiveRunView` / `HistoryRunView`.
 */
export function Workspace({ savedRunId }: { savedRunId?: string }) {
  const hook = useAnalysisStreamContext();
  const router = useRouter();

  const [hist, setHist]           = useState<HistState>(EMPTY_HIST);
  const [collapsed, setCollapsed] = useState(false);
  // Mobile-only: the runs panel becomes a slide-in drawer below `lg`. On
  // desktop it's a permanent column and this flag is ignored.
  const [navOpen, setNavOpen]     = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);

  const isLiveActive = hook.status !== "idle";
  // View is derived, not stored: the route (savedRunId) is the source of truth
  // for the history view; otherwise show the live run if one is active, else
  // the empty dashboard.
  const view: View = savedRunId
    ? { kind: "history", id: savedRunId }
    : isLiveActive ? { kind: "live" } : { kind: "empty" };

  // Arriving via `/?new=1` (from a "New Project" click on a saved-run page)
  // auto-opens the upload dialog on the dashboard, then strips the param.
  useEffect(() => {
    if (savedRunId || typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("new")) {
      setDialogOpen(true);
      window.history.replaceState(null, "", "/");
    }
  }, [savedRunId]);

  // Refresh the runs list once a live run reaches a terminal state, so the
  // freshly-persisted run shows up in history.
  const lastStatus = useRef(hook.status);
  useEffect(() => {
    if (lastStatus.current !== hook.status && (hook.status === "done" || hook.status === "error")) {
      setRefreshSignal((n) => n + 1);
    }
    lastStatus.current = hook.status;
  }, [hook.status]);

  // Load a historical run (results + re-signed viewer sources) for the route's
  // saved-run id. Keyed on `savedRunId` (a string) — NOT the derived `view`
  // object, which is recreated every render and would loop the effect.
  useEffect(() => {
    if (!savedRunId) return;
    const runId = savedRunId;
    let cancelled = false;
    setHist({ ...EMPTY_HIST, loading: true });
    (async () => {
      try {
        const [res, cached] = await Promise.all([
          getAnalysis(runId),
          resignRunSource(runId),
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
          const fromServer = await resignStoragePaths(runId, {
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
  }, [savedRunId]);

  const handleRun = useCallback((file3d: File, file2d: File, batch: number, partType: string | null) => {
    setDialogOpen(false);
    // Live runs always run at the dashboard route; the derived view flips to
    // "live" as soon as the hook leaves idle.
    void hook.run(file3d, file2d, batch, partType);
  }, [hook]);

  const handleSelectRun = useCallback((id: string) => {
    setNavOpen(false); // close the mobile drawer after picking a run
    // The in-flight live run lives at "/"; saved runs get their own URL.
    if (id === hook.analysisId) router.push("/");
    else router.push(`/save-run/${id}`);
  }, [hook.analysisId, router]);

  const handleNewProject = useCallback(() => {
    setNavOpen(false);
    // On a saved-run page, go to the dashboard and auto-open the dialog there
    // (live runs must run at "/"). On the dashboard, just open it.
    if (savedRunId) router.push("/?new=1");
    else setDialogOpen(true);
  }, [savedRunId, router]);

  const activeId = savedRunId ?? (isLiveActive ? hook.analysisId : null);

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
        onNewEstimate={handleNewProject}
        liveRun={liveRun}
        refreshSignal={refreshSignal}
        mobileOpen={navOpen}
        onMobileClose={() => setNavOpen(false)}
      />

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Mobile top bar — hamburger to open the runs drawer. Hidden on lg+
           where the runs panel is a permanent column. */}
        <div className="flex items-center gap-2 border-b border-border px-3 py-2 lg:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label="Open projects panel"
          >
            <Menu className="h-5 w-5" />
          </button>
          <BrandMark />
        </div>

        {view.kind === "empty" ? (
          <EmptyState onNewEstimate={handleNewProject} />
        ) : view.kind === "live" ? (
          <LiveRunView key={hook.analysisId ?? "live"} hook={hook} onNewEstimate={handleNewProject} />
        ) : (
          <HistoryRunView key={view.id} hist={hist} analysisId={view.id} onNewEstimate={handleNewProject} />
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
