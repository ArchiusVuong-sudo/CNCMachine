"use client";

/**
 * SSE driver for ``POST /api/v1/analyze-stream``.
 *
 * Wires the FE's upload → analyze flow to the new Python backend.
 *
 *  - Upload: FE → Supabase Storage (bypasses the API server because
 *    file bytes are bigger than we want to buffer through a proxy).
 *    Signed URLs are generated client-side and passed to the server.
 *  - Stream: FE → ``/api/v1/analyze-stream`` (catch-all proxy at
 *    ``src/app/api/v1/[...path]/route.ts``) → Python.
 *  - Result: the orchestrator persists the full ``results`` envelope to
 *    ``KNOWLEDGE_BASE/_research/notes/<id>_full.json`` via
 *    ``write_full_result`` immediately before emitting ``final_answer``.
 *    No save call from the FE.
 *
 * Auth is single-user — ``user_id`` is always ``null``.
 */

import { useCallback, useRef, useState } from "react";
import { createSupabaseBrowserClient } from "@/lib/supabase-browser";
import { parseSSEBuffer } from "@/lib/api/client";
import { saveRunSource } from "@/lib/run-sources";
import type {
  AgentStreamMessage,
  AgenticData,
  BBox,
  ComponentCost,
  Component as WireComponent,
  FinalAnswer,
  Feature,
  RoutingRow,
} from "@/lib/api/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

export type PipelineStatus = "idle" | "uploading" | "streaming" | "done" | "error";

/**
 * Fresh viewer sources for the *current* run. The viewport reads these
 * immediately (no re-sign round-trip); paths are also persisted to
 * localStorage so the same run can be reopened later from the runs panel.
 */
export interface UploadedSources {
  stepUrl:      string;
  drawingUrl:   string;
  drawingType?: string;
  fileName?:    string;
  stepPath:     string;
  drawingPath:  string;
}

/** Per-component state assembled live from SSE + final_answer. */
export interface CanvasComponent {
  index:        number;
  name?:        string;
  partType?:    string;
  material?:    string;
  bbox?:        BBox;
  features?:    Feature[];
  /** Routing rows once the per-component agent finishes (filled on final_answer). */
  processes?:   RoutingRow[];
  /** Agentic engine output (Phase A→D). Filled on final_answer. */
  agentic?:     AgenticData;
  cost?:        ComponentCost;
  cycleTimeMin?: number;
  totalUsd?:    number;
  isRunning:    boolean;
}

export interface AnalysisStreamState {
  status:           PipelineStatus;
  error:            string | null;
  analysisId:       string | null;
  messages:         AgentStreamMessage[];
  liveThinking:     string;
  completedTools:   Set<string>;
  activeTool:       string | null;
  results:          FinalAnswer | null;
  totalMinutes:     number | null;
  totalUsd:         number | null;
  batchSize:        number;
  sources:          UploadedSources | null;
  canvasComponents: Record<number, CanvasComponent>;
  isStreaming:      boolean;
  isLoading:        boolean;
  isDone:           boolean;
  hasError:         boolean;
}

/** Pull routing rows off a component dump, preferring the new name. */
function readProcesses(comp: WireComponent): RoutingRow[] | undefined {
  return comp.manufacturing_processes ?? comp.processes;
}

export function useAnalysisStream() {
  const [status,          setStatus]         = useState<PipelineStatus>("idle");
  const [error,           setError]          = useState<string | null>(null);
  const [analysisId,      setAnalysisId]     = useState<string | null>(null);
  const [messages,        setMessages]       = useState<AgentStreamMessage[]>([]);
  const [liveThinking,    setLiveThinking]   = useState("");
  const [completedTools,  setCompletedTools] = useState<Set<string>>(new Set());
  const [activeTool,      setActiveTool]     = useState<string | null>(null);
  const [results,         setResults]        = useState<FinalAnswer | null>(null);
  const [totalMinutes,    setTotalMinutes]   = useState<number | null>(null);
  const [totalUsd,        setTotalUsd]       = useState<number | null>(null);
  const [batchSize,       setBatchSize]      = useState<number>(1);
  const [sources,         setSources]        = useState<UploadedSources | null>(null);
  const [canvasComponents, setCanvasComponents] = useState<Record<number, CanvasComponent>>({});

  const abortRef = useRef<AbortController | null>(null);

  const addMsg = useCallback((type: string, data: Record<string, unknown>) => {
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), type, data, timestamp: Date.now() },
    ]);
  }, []);

  // Mark all in-flight rows as completed when the pipeline reaches a terminal
  // state (final_answer / done / error). Catches the final `status` event and
  // any tool_call whose matching tool_result never arrived (server hiccup,
  // cancellation, etc.) so the activity feed doesn't spin forever.
  const completePendingStatuses = useCallback(() => {
    setMessages((prev) => prev.map((m) => {
      if (m.type === "status") {
        const d = m.data as { completed?: boolean; failed?: boolean };
        if (!d.completed && !d.failed) return { ...m, data: { ...m.data, completed: true } };
      }
      if (m.type === "tool_call") {
        return {
          ...m,
          type: "tool_result",
          data: {
            ...m.data,
            result: { auto_completed: true, note: "no tool_result event was received before pipeline end" },
            duration_ms: 0,
            failed: false,
          },
        };
      }
      return m;
    }));
  }, []);

  const run = useCallback(async (
    file3d:                 File,
    file2d:                 File,
    batch:                  number = 1,
    forcedAssemblyPartType: string | null = null,
  ) => {
    setBatchSize(batch);
    setStatus("uploading");
    setError(null);
    setMessages([]);
    setLiveThinking("");
    setCompletedTools(new Set());
    setActiveTool(null);
    setResults(null);
    setTotalMinutes(null);
    setTotalUsd(null);
    setSources(null);
    setCanvasComponents({});

    try {
      const sbClient = createSupabaseBrowserClient();
      const runId    = crypto.randomUUID();
      setAnalysisId(runId);

      const file3dPath = `uploads/cnc/${runId}/3d_${file3d.name}`;
      const file2dPath = `uploads/cnc/${runId}/2d_${file2d.name}`;

      // ── Upload to Supabase Storage (FE → Storage; bytes don't hit our API) ─
      const [up3d, up2d] = await Promise.all([
        sbClient.storage.from("parts").upload(file3dPath, file3d, {
          contentType: "application/step", upsert: true,
        }),
        sbClient.storage.from("parts").upload(file2dPath, file2d, {
          contentType: file2d.type || "application/octet-stream", upsert: true,
        }),
      ]);
      if (up3d.error) throw new Error(`3D upload failed: ${up3d.error.message}`);
      if (up2d.error) throw new Error(`2D upload failed: ${up2d.error.message}`);

      const [sign3d, sign2d] = await Promise.all([
        sbClient.storage.from("parts").createSignedUrl(file3dPath, 86400),
        sbClient.storage.from("parts").createSignedUrl(file2dPath, 86400),
      ]);
      if (sign3d.error) throw new Error(`Signed URL 3D: ${sign3d.error.message}`);
      if (sign2d.error) throw new Error(`Signed URL 2D: ${sign2d.error.message}`);

      // Surface fresh viewer URLs immediately, and persist the durable storage
      // *paths* (keyed by analysis id) so the run can be reopened later — the
      // signed URLs expire in 24h but the paths never do.
      setSources({
        stepUrl:     sign3d.data!.signedUrl,
        drawingUrl:  sign2d.data!.signedUrl,
        drawingType: file2d.type || undefined,
        fileName:    file3d.name,
        stepPath:    file3dPath,
        drawingPath: file2dPath,
      });
      saveRunSource({
        analysisId:  runId,
        fileName:    file3d.name,
        stepPath:    file3dPath,
        drawingPath: file2dPath,
        drawingType: file2d.type || undefined,
        createdAt:   Date.now(),
      });

      // ── Open SSE stream via the API v1 catch-all proxy ─────────────────────
      setStatus("streaming");
      const controller = new AbortController();
      abortRef.current = controller;

      const resp = await fetch("/api/v1/analyze-stream", {
        method:  "POST",
        headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
        body: JSON.stringify({
          analysis_id:               runId,
          drawing_url:               sign2d.data!.signedUrl,
          step_url:                  sign3d.data!.signedUrl,
          file_name:                 file3d.name,
          user_id:                   null,
          batch_size:                batch,
          forced_assembly_part_type: forcedAssemblyPartType,
        }),
        signal: controller.signal,
      });

      if (!resp.ok || !resp.body) throw new Error(`Stream error: ${resp.status}`);

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer        = "";
      let localThinking = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const { events, remaining } = parseSSEBuffer(buffer);
        buffer = remaining;

        for (const { event, data } of events) {
          const parsed = (typeof data === "object" && data !== null) ? data as any : {};

          switch (event) {
            case "status":
              setMessages((prev) => {
                const next = prev.map((m) =>
                  m.type === "status" && !(m.data as any).completed && !(m.data as any).failed
                    ? { ...m, data: { ...m.data, completed: true } }
                    : m
                );
                return [...next, { id: crypto.randomUUID(), type: "status", data: parsed, timestamp: Date.now() }];
              });
              break;

            case "thinking":
              localThinking += parsed.content || "";
              setLiveThinking(localThinking);
              break;

            case "tool_call":
              if (localThinking) {
                addMsg("thinking", { content: localThinking, iteration: parsed.iteration });
                setLiveThinking("");
                localThinking = "";
              }
              setActiveTool(parsed.tool);
              addMsg("tool_call", parsed);
              break;

            case "tool_result":
              setActiveTool(null);
              setCompletedTools((prev) => new Set(prev).add(parsed.tool));
              setMessages((prev) => {
                const hasErr = !!(parsed.result as any)?.error;
                const next   = [...prev];
                // Pair to the first matching tool_call (preferring an exact
                // iteration match when present). Replace-all would flip every
                // same-named tool_call when only one matched, leaving later
                // tool_results unpaired and the rows stuck on the spinner.
                const wantIter = parsed.iteration;
                let matchIdx = -1;
                for (let i = 0; i < next.length; i++) {
                  const m = next[i];
                  if (m.type !== "tool_call") continue;
                  const md = m.data as any;
                  if (md.tool !== parsed.tool) continue;
                  if (wantIter != null && md.iteration != null && md.iteration !== wantIter) continue;
                  matchIdx = i;
                  break;
                }
                if (matchIdx >= 0) {
                  const m  = next[matchIdx];
                  next[matchIdx] = { ...m, type: "tool_result", data: { ...m.data, ...parsed, failed: hasErr } };
                } else {
                  next.push({ id: crypto.randomUUID(), type: "tool_result", data: { ...parsed, failed: hasErr }, timestamp: Date.now() });
                }
                return next;
              });
              break;

            case "final_answer": {
              if (localThinking) {
                addMsg("thinking", { content: localThinking });
                setLiveThinking("");
                localThinking = "";
              }
              completePendingStatuses();

              const envelope = parsed as { results?: FinalAnswer; summary?: string };
              const fa = (envelope.results ?? parsed) as FinalAnswer;
              setResults(fa);
              setTotalMinutes(typeof fa.total_minutes === "number" ? fa.total_minutes : null);
              setTotalUsd(typeof fa.total_usd === "number" ? fa.total_usd : null);

              // Fill per-component canvas state from the results envelope.
              setCanvasComponents(() => {
                const next: Record<number, CanvasComponent> = {};
                for (const comp of fa.components ?? []) {
                  const idx = comp.component_index;
                  const procs = readProcesses(comp);
                  next[idx] = {
                    index:        idx,
                    name:         comp.name,
                    partType:     comp.part_type,
                    material:     comp.material,
                    bbox:         comp.bbox,
                    features:     comp.features,
                    processes:    procs,
                    agentic:      comp.agentic,
                    cost:         comp.cost,
                    cycleTimeMin: typeof comp.cycle_time_min === "number" ? comp.cycle_time_min : undefined,
                    totalUsd:     comp.cost?.total_usd,
                    isRunning:    false,
                  };
                }
                return next;
              });

              addMsg("final_answer", parsed);
              break;
            }

            case "done":
              completePendingStatuses();
              addMsg("done", parsed);
              setStatus((s) => (s === "error" ? "error" : "done"));
              break;

            case "error":
              if (localThinking) {
                addMsg("thinking", { content: localThinking });
                setLiveThinking("");
                localThinking = "";
              }
              completePendingStatuses();
              setStatus("error");
              setError(parsed.message || "Analysis error");
              addMsg("error", parsed);
              break;

            case "heartbeat":
              break;

            case "warning":
              // Best-effort backend warnings — non-fatal but worth surfacing
              // (e.g. BOM mapping crash, per-component chain crash).
              addMsg("warning", parsed);
              break;
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const msg = err instanceof Error ? err.message : "Something went wrong";
        setError(msg);
        setStatus("error");
        addMsg("error", { message: msg });
      }
    } finally {
      setStatus((s) => (s === "uploading" || s === "streaming" ? "error" : s));
      setActiveTool(null);
      abortRef.current = null;
    }
  }, [addMsg, completePendingStatuses]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    addMsg("error", { message: "Processing cancelled." });
    setLiveThinking("");
    setStatus("error");
  }, [addMsg]);

  const reset = useCallback(() => {
    setStatus("idle");
    setError(null);
    setAnalysisId(null);
    setMessages([]);
    setLiveThinking("");
    setCompletedTools(new Set());
    setActiveTool(null);
    setResults(null);
    setTotalMinutes(null);
    setTotalUsd(null);
    setSources(null);
    setCanvasComponents({});
  }, []);

  return {
    status,
    error,
    analysisId,
    messages,
    liveThinking,
    completedTools,
    activeTool,
    results,
    totalMinutes,
    totalUsd,
    batchSize,
    sources,
    canvasComponents,
    run,
    cancel,
    reset,
    isStreaming: status === "streaming",
    isLoading:   status === "uploading",
    isDone:      status === "done",
    hasError:    status === "error",
  };
}
