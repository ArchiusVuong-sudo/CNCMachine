"use client";

/**
 * Root-level provider for the live analysis SSE stream.
 *
 * The workspace renders at two routes — `/` (dashboard / live run) and
 * `/save-run/<id>` (a saved run). Those are separate page components, so
 * navigating between them unmounts and remounts <Workspace>. If the SSE hook
 * lived inside <Workspace>, that remount would destroy the in-flight stream
 * state and the live run would *look* stopped even though the API keeps running
 * in the background.
 *
 * Hosting the hook here — in a provider mounted by the root layout, which never
 * unmounts during client navigation — keeps the stream and its loading state
 * alive across route changes. The runs panel keeps spinning while the API runs.
 */
import { createContext, useContext } from "react";
import { useAnalysisStream } from "./useAnalysisStream";

type AnalysisStreamCtx = ReturnType<typeof useAnalysisStream>;

const AnalysisStreamContext = createContext<AnalysisStreamCtx | null>(null);

export function AnalysisStreamProvider({ children }: { children: React.ReactNode }) {
  const hook = useAnalysisStream();
  return <AnalysisStreamContext.Provider value={hook}>{children}</AnalysisStreamContext.Provider>;
}

export function useAnalysisStreamContext(): AnalysisStreamCtx {
  const ctx = useContext(AnalysisStreamContext);
  if (!ctx) throw new Error("useAnalysisStreamContext must be used within <AnalysisStreamProvider>");
  return ctx;
}
