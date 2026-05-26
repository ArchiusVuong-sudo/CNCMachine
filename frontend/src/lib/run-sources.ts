"use client";

/**
 * Per-run viewer-source cache.
 *
 * The browser uploads the STEP + drawing to Supabase Storage (bucket
 * "parts") and the analysis only ever sees short-lived signed URLs. To let
 * the viewport show geometry again when a *past* run is reopened from the
 * runs panel, we persist the storage *paths* (which never expire) keyed by
 * analysis_id in localStorage, then re-sign on demand. Signed URLs are cheap
 * and short-lived; the path is the durable handle.
 */
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";

const BUCKET = "parts";
const LS_KEY = "cofab:run-sources";
const RESIGN_TTL_SEC = 3600;

export interface RunSource {
  analysisId: string;
  fileName?: string;
  stepPath?: string;
  drawingPath?: string;
  drawingType?: string;
  createdAt: number;
}

/** Live URLs handed to the viewport — null when geometry isn't available. */
export interface ViewerSources {
  stepUrl: string | null;
  drawingUrl: string | null;
  drawingType?: string | null;
  fileName?: string | null;
}

type Store = Record<string, RunSource>;

function readStore(): Store {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(LS_KEY) || "{}") as Store;
  } catch {
    return {};
  }
}

function writeStore(store: Store) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(store));
  } catch {
    /* quota / private mode — non-fatal */
  }
}

export function saveRunSource(src: RunSource) {
  const store = readStore();
  store[src.analysisId] = { ...store[src.analysisId], ...src };
  // Keep the cache bounded — newest 50 runs.
  const entries = Object.values(store).sort((a, b) => b.createdAt - a.createdAt);
  if (entries.length > 50) {
    const keep: Store = {};
    for (const e of entries.slice(0, 50)) keep[e.analysisId] = e;
    writeStore(keep);
  } else {
    writeStore(store);
  }
}

export function getRunSource(analysisId: string): RunSource | null {
  return readStore()[analysisId] ?? null;
}

/** Re-sign the cached storage paths into fresh viewer URLs. */
export async function resignRunSource(analysisId: string): Promise<ViewerSources | null> {
  const src = getRunSource(analysisId);
  if (!src) return null;

  const sb = createSupabaseBrowserClient();
  let stepUrl: string | null = null;
  let drawingUrl: string | null = null;

  if (src.stepPath) {
    const { data } = await sb.storage.from(BUCKET).createSignedUrl(src.stepPath, RESIGN_TTL_SEC);
    stepUrl = data?.signedUrl ?? null;
  }
  if (src.drawingPath) {
    const { data } = await sb.storage.from(BUCKET).createSignedUrl(src.drawingPath, RESIGN_TTL_SEC);
    drawingUrl = data?.signedUrl ?? null;
  }

  return { stepUrl, drawingUrl, drawingType: src.drawingType, fileName: src.fileName };
}
