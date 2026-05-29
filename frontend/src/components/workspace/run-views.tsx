"use client";

import { Loader2, AlertCircle } from "lucide-react";
import { headerTitle } from "@/lib/domain/results-adapter";
import type { useAnalysisStream } from "@/lib/hooks/useAnalysisStream";
import { TopBar, ScrollBody, InfoCard } from "./chrome";
import { PipelineActivityCard } from "./pipeline-activity-card";
import { ResultsLayout } from "./results-layout";
import type { HistState, ViewerSrc } from "./types";

/* ──────────────────────────────────────────────────────────────────────────
 * Live run view (driven by the SSE hook)
 * ────────────────────────────────────────────────────────────────────────── */

export function LiveRunView({
  hook, onNewEstimate,
}: {
  hook: ReturnType<typeof useAnalysisStream>;
  onNewEstimate: () => void;
}) {
  const { results, sources, status, messages, liveThinking, isStreaming, isLoading, error } = hook;
  const fileName = sources?.fileName ?? results?.file_name ?? "New project";
  const title = headerTitle(results?.vlm_extraction, fileName);

  const statusBadge =
    isLoading ? { label: "Uploading…", tone: "info" as const } :
    isStreaming ? { label: "Analyzing…", tone: "info" as const } :
    status === "done" ? { label: "Complete", tone: "secondary" as const } :
    status === "error" ? { label: "Failed", tone: "destructive" as const } : null;

  const viewer: ViewerSrc = {
    stepUrl:     sources?.stepUrl ?? null,
    drawingUrl:  sources?.drawingUrl ?? null,
    drawingType: sources?.drawingType ?? null,
    fileName:    sources?.fileName ?? null,
  };

  const hasResults = !!results;
  // Keep the pipeline feed on the page even after results land — it just
  // auto-collapses (see PipelineActivityCard) so the estimate stays on top.
  const showTimeline = isLoading || isStreaming || messages.length > 0;

  return (
    <>
      <TopBar
        title={title}
        statusBadge={statusBadge}
        streaming={isStreaming}
        onStop={hook.cancel}
        onNewEstimate={onNewEstimate}
      />
      <ScrollBody>
        {isLoading && (
          <InfoCard icon={<Loader2 className="h-4 w-4 animate-spin text-primary" />} title="Uploading files">
            Sending your STEP and drawing to storage…
          </InfoCard>
        )}

        {(hasResults || viewer.stepUrl || viewer.drawingUrl) && (
          <ResultsLayout results={results} viewer={viewer} analysisId={hook.analysisId} />
        )}

        {showTimeline && (
          <PipelineActivityCard
            messages={messages}
            liveThinking={liveThinking}
            isStreaming={isStreaming}
            collapsed={hasResults}
          />
        )}

        {error && !hasResults && (
          <InfoCard icon={<AlertCircle className="h-4 w-4 text-destructive" />} title="Analysis failed" tone="error">
            {error}
          </InfoCard>
        )}
      </ScrollBody>
    </>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
 * Historical run view (loaded from /v1/analyses/{id})
 * ────────────────────────────────────────────────────────────────────────── */

export function HistoryRunView({
  hist, analysisId, onNewEstimate,
}: {
  hist: HistState;
  analysisId: string;
  onNewEstimate: () => void;
}) {
  const { results, sources, loading, error } = hist;
  const fileName = sources?.fileName ?? results?.file_name ?? analysisId;
  const title = headerTitle(results?.vlm_extraction, fileName);

  const statusBadge =
    loading ? { label: "Loading…", tone: "info" as const } :
    error ? { label: "Failed to load", tone: "destructive" as const } :
    { label: "Saved run", tone: "secondary" as const };

  const viewer: ViewerSrc = {
    stepUrl:     sources?.stepUrl ?? null,
    drawingUrl:  sources?.drawingUrl ?? null,
    drawingType: sources?.drawingType ?? null,
    fileName:    sources?.fileName ?? null,
  };

  return (
    <>
      <TopBar title={title} statusBadge={statusBadge} onNewEstimate={onNewEstimate} />
      <ScrollBody>
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
            <ResultsLayout results={results} viewer={viewer} analysisId={analysisId} />
            {results.messages && results.messages.length > 0 && (
              <PipelineActivityCard
                messages={results.messages}
                liveThinking=""
                isStreaming={false}
                collapsed={true}
              />
            )}
          </>
        ) : (
          <InfoCard icon={<AlertCircle className="h-4 w-4 text-muted-foreground" />} title="No data">
            This run has no stored results.
          </InfoCard>
        )}
      </ScrollBody>
    </>
  );
}
