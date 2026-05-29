import type { FinalAnswer } from "@/lib/api/types";
import type { ViewerSources } from "@/lib/run-sources";

/** Re-signed file URLs the viewport renders (3D STEP + 2D drawing). */
export interface ViewerSrc {
  stepUrl: string | null;
  drawingUrl: string | null;
  drawingType?: string | null;
  fileName?: string | null;
}

/** A loaded historical run: results envelope + re-signed viewer sources. */
export interface HistState {
  results: FinalAnswer | null;
  sources: ViewerSources | null;
  loading: boolean;
  error: string | null;
}

export const EMPTY_HIST: HistState = { results: null, sources: null, loading: false, error: null };
