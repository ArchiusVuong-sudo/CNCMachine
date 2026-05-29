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

/** Explicit storage paths, typically the server envelope's `sources` block. */
export interface StoragePathRef {
  bucket?: string | null;
  stepPath?: string | null;
  drawingPath?: string | null;
  fileName?: string | null;
}

/** Best-effort MIME type for a drawing path, inferred from its extension. */
function inferDrawingType(path?: string | null): string | null {
  if (!path) return null;
  const ext = path.split("?")[0].split(".").pop()?.toLowerCase();
  if (ext === "pdf") return "application/pdf";
  if (ext === "png") return "image/png";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  return null;
}

/**
 * Sign explicit storage paths into fresh viewer URLs — the durable fallback
 * when this browser's localStorage source cache has no entry for the run
 * (run opened on a different machine, or after the cache was cleared). The
 * paths come from the server results envelope, which is shared across all
 * browsers, so geometry renders everywhere a run is reopened.
 *
 * Side effect: caches the resolved paths back into localStorage so the next
 * reopen on this browser is a plain {@link resignRunSource}.
 *
 * Returns null when there is nothing signable (no paths at all).
 */
export async function resignStoragePaths(
  analysisId: string,
  ref: StoragePathRef,
): Promise<ViewerSources | null> {
  const stepPath = ref.stepPath || undefined;
  const drawingPath = ref.drawingPath || undefined;
  if (!stepPath && !drawingPath) return null;

  const bucket = ref.bucket || BUCKET;
  const sb = createSupabaseBrowserClient();
  let stepUrl: string | null = null;
  let drawingUrl: string | null = null;

  if (stepPath) {
    const { data } = await sb.storage.from(bucket).createSignedUrl(stepPath, RESIGN_TTL_SEC);
    stepUrl = data?.signedUrl ?? null;
  }
  if (drawingPath) {
    const { data } = await sb.storage.from(bucket).createSignedUrl(drawingPath, RESIGN_TTL_SEC);
    drawingUrl = data?.signedUrl ?? null;
  }

  const drawingType = inferDrawingType(drawingPath);

  // Warm the localStorage cache so the next reopen on this browser is cheap.
  if (stepPath || drawingPath) {
    saveRunSource({
      analysisId,
      fileName: ref.fileName ?? undefined,
      stepPath,
      drawingPath,
      drawingType: drawingType ?? undefined,
      createdAt: Date.now(),
    });
  }

  return { stepUrl, drawingUrl, drawingType, fileName: ref.fileName ?? null };
}
