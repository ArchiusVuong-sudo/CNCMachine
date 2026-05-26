"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Plus, X, Loader2, Cpu, Sparkles, PackageOpen, AlertCircle, Activity,
} from "lucide-react";
import type { FinalAnswer } from "@/lib/api/types";
import { useApproach4 } from "@/lib/hooks/useApproach4";
import { getAnalysis } from "@/lib/api/client";
import { resignRunSource, type ViewerSources } from "@/lib/run-sources";
import { Viewport } from "@/components/viewport/viewport";
import { ExtractionPanel } from "@/components/extraction/extraction-panel";
import { ResultsPanel } from "@/components/results/results-panel";
import { ProgressTimeline } from "./progress-timeline";
import { RunsPanel } from "./runs-panel";
import { NewEstimateDialog } from "./new-estimate-dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type View =
  | { kind: "empty" }
  | { kind: "live" }
  | { kind: "history"; id: string };

interface HistState {
  results: FinalAnswer | null;
  sources: ViewerSources | null;
  loading: boolean;
  error: string | null;
}

const EMPTY_HIST: HistState = { results: null, sources: null, loading: false, error: null };

export function Workspace() {
  const hook = useApproach4();

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
        const [res, src] = await Promise.all([
          getAnalysis(view.id),
          resignRunSource(view.id),
        ]);
        if (cancelled) return;
        setHist({ results: res as FinalAnswer, sources: src, loading: false, error: null });
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
        label: hook.sources?.fileName ?? "New estimate",
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
          <LiveRunView hook={hook} onNewEstimate={() => setDialogOpen(true)} />
        ) : (
          <HistoryRunView hist={hist} analysisId={view.id} onNewEstimate={() => setDialogOpen(true)} />
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

/* ──────────────────────────────────────────────────────────────────────────
 * Shared chrome
 * ────────────────────────────────────────────────────────────────────────── */

function TopBar({
  fileName, status, components, batch, streaming, onStop, onNewEstimate,
}: {
  fileName: string;
  status: string;
  components: number;
  batch: number;
  streaming?: boolean;
  onStop?: () => void;
  onNewEstimate: () => void;
}) {
  return (
    <div className="flex shrink-0 items-center gap-3 border-b border-border bg-background px-4 py-2.5">
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold text-foreground" title={fileName}>{fileName}</div>
        <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <span>{status}</span>
          {components > 0 && (
            <>
              <span className="text-muted-foreground/40">·</span>
              <span className="inline-flex items-center gap-1"><PackageOpen className="h-3 w-3" />{components} comp{components !== 1 ? "s" : ""}</span>
            </>
          )}
          {batch > 1 && (
            <>
              <span className="text-muted-foreground/40">·</span>
              <span>batch ×{batch}</span>
            </>
          )}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {streaming && onStop && (
          <Button variant="destructive" size="sm" className="gap-1.5" onClick={onStop}>
            <X className="h-3.5 w-3.5" /> Stop
          </Button>
        )}
        <Button variant="outline" size="sm" className="gap-1.5" onClick={onNewEstimate}>
          <Plus className="h-3.5 w-3.5" /> New estimate
        </Button>
      </div>
    </div>
  );
}

/** Two-up body: sticky viewport on the left, scrolling detail on the right. */
function Body({
  viewer, children,
}: {
  viewer: { stepUrl: string | null; drawingUrl: string | null; drawingType?: string | null; fileName?: string | null };
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden xl:flex-row">
      <div className="h-[360px] shrink-0 border-b border-border p-3 xl:h-auto xl:w-[44%] xl:border-b-0 xl:border-r">
        <Viewport
          stepUrl={viewer.stepUrl}
          drawingUrl={viewer.drawingUrl}
          drawingType={viewer.drawingType}
          fileName={viewer.fileName}
          className="h-full"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-3xl space-y-4">{children}</div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Empty state
 * ────────────────────────────────────────────────────────────────────────── */

function EmptyState({ onNewEstimate }: { onNewEstimate: () => void }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="max-w-md space-y-6 text-center">
        <div className="brand-gradient mx-auto flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg">
          <Cpu className="h-8 w-8 text-white" />
        </div>
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-3.5 py-1">
            <Sparkles className="h-3 w-3 text-primary" />
            <span className="text-[11px] font-bold uppercase tracking-widest text-primary/80">CNC Costing AI</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Manufacturing cost estimator</h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Upload a 3D STEP model and 2D drawing. The pipeline extracts features, plans the
            machining process, and returns a per-component cost estimate you can review and correct.
          </p>
        </div>
        <Button size="lg" className="gap-2" onClick={onNewEstimate}>
          <Plus className="h-4 w-4" /> Start a new estimate
        </Button>
        <p className="text-xs text-muted-foreground/70">…or pick a past run from the panel on the left.</p>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Live run view (driven by the SSE hook)
 * ────────────────────────────────────────────────────────────────────────── */

function LiveRunView({
  hook, onNewEstimate,
}: {
  hook: ReturnType<typeof useApproach4>;
  onNewEstimate: () => void;
}) {
  const { results, sources, status, messages, liveThinking, isStreaming, isLoading, error } = hook;
  const fileName  = sources?.fileName ?? results?.file_name ?? "New estimate";
  const compCount = results?.components?.length ?? results?.assembly_data?.component_count ?? 0;
  const batch     = results?.batch_size ?? hook.batchSize ?? 1;

  const statusLabel =
    isLoading ? "Uploading…" :
    isStreaming ? "Analyzing…" :
    status === "done" ? "Complete" :
    status === "error" ? "Failed" : "Idle";

  const viewer = {
    stepUrl:     sources?.stepUrl ?? null,
    drawingUrl:  sources?.drawingUrl ?? null,
    drawingType: sources?.drawingType ?? null,
    fileName:    sources?.fileName ?? null,
  };

  const hasResults = !!results;
  const showTimeline = isLoading || isStreaming || (!hasResults && messages.length > 0);

  return (
    <>
      <TopBar
        fileName={fileName}
        status={statusLabel}
        components={compCount}
        batch={batch}
        streaming={isStreaming}
        onStop={hook.cancel}
        onNewEstimate={onNewEstimate}
      />
      <Body viewer={viewer}>
        {isLoading && (
          <InfoCard icon={<Loader2 className="h-4 w-4 animate-spin text-primary" />} title="Uploading files">
            Sending your STEP and drawing to storage…
          </InfoCard>
        )}

        {showTimeline && (
          <div className="rounded-xl border border-border bg-card">
            <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
              <Activity className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold">Pipeline activity</span>
              {isStreaming && <Badge variant="info" className="ml-1 text-[10px]">Live</Badge>}
            </div>
            <div className="max-h-[420px] overflow-y-auto p-3">
              <ProgressTimeline messages={messages} liveThinking={liveThinking} isStreaming={isStreaming} />
            </div>
          </div>
        )}

        {error && !hasResults && (
          <InfoCard icon={<AlertCircle className="h-4 w-4 text-destructive" />} title="Analysis failed" tone="error">
            {error}
          </InfoCard>
        )}

        {hasResults && (
          <>
            <ExtractionPanel results={results} />
            <ResultsPanel results={results} analysisId={hook.analysisId} />
          </>
        )}
      </Body>
    </>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Historical run view (loaded from /v1/analyses/{id})
 * ────────────────────────────────────────────────────────────────────────── */

function HistoryRunView({
  hist, analysisId, onNewEstimate,
}: {
  hist: HistState;
  analysisId: string;
  onNewEstimate: () => void;
}) {
  const { results, sources, loading, error } = hist;
  const fileName  = sources?.fileName ?? results?.file_name ?? analysisId;
  const compCount = results?.components?.length ?? results?.assembly_data?.component_count ?? 0;
  const batch     = results?.batch_size ?? 1;

  const viewer = {
    stepUrl:     sources?.stepUrl ?? null,
    drawingUrl:  sources?.drawingUrl ?? null,
    drawingType: sources?.drawingType ?? null,
    fileName:    sources?.fileName ?? null,
  };

  return (
    <>
      <TopBar
        fileName={fileName}
        status={loading ? "Loading…" : error ? "Failed to load" : "Saved run"}
        components={compCount}
        batch={batch}
        onNewEstimate={onNewEstimate}
      />
      <Body viewer={viewer}>
        {loading ? (
          <InfoCard icon={<Loader2 className="h-4 w-4 animate-spin text-primary" />} title="Loading run">
            Fetching the saved estimate…
          </InfoCard>
        ) : error ? (
          <InfoCard icon={<AlertCircle className="h-4 w-4 text-destructive" />} title="Couldn’t load run" tone="error">
            {error}
          </InfoCard>
        ) : results ? (
          <>
            {!viewer.stepUrl && !viewer.drawingUrl && (
              <InfoCard icon={<AlertCircle className="h-4 w-4 text-amber-500" />} title="Geometry unavailable" tone="warn">
                The original files for this run aren’t cached in this browser, so the viewport is empty.
                The extracted data and cost breakdown below are still available.
              </InfoCard>
            )}
            <ExtractionPanel results={results} />
            <ResultsPanel results={results} analysisId={analysisId} />
          </>
        ) : (
          <InfoCard icon={<AlertCircle className="h-4 w-4 text-muted-foreground" />} title="No data">
            This run has no stored results.
          </InfoCard>
        )}
      </Body>
    </>
  );
}

function InfoCard({
  icon, title, children, tone = "default",
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
  tone?: "default" | "error" | "warn";
}) {
  return (
    <div className={cn(
      "rounded-xl border px-4 py-3.5",
      tone === "error" ? "border-red-200 bg-red-50" :
      tone === "warn" ? "border-amber-200 bg-amber-50" :
      "border-border bg-card",
    )}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm font-semibold text-foreground">{title}</span>
      </div>
      <p className="mt-1 pl-6 text-[13px] text-muted-foreground">{children}</p>
    </div>
  );
}
