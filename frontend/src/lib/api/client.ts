/**
 * Tiny typed client for the FE → ``/api/v1/*`` proxy.
 *
 * Every helper goes through ``/api/v1/...``; nothing here imports
 * ``supabase-browser`` or the upstream Python URL. The actual proxying
 * happens in ``src/app/api/v1/[...path]/route.ts``.
 *
 * SSE is exposed via :func:`analyzeStream`. It opens
 * ``POST /api/v1/analyze-stream``, parses the ``event: foo / data: {...}``
 * frames, and emits parsed events through an async callback. The hook
 * (``useAnalysisStream``) consumes them.
 */
import type {
  AnalysisListResponse,
  FinalAnswer,
  HealthResponse,
  LaborRateCreate,
  LaborRateRow,
  MachineCreate,
  MachineRow,
  MaterialStockCreate,
  MaterialStockRow,
  ToolingCreate,
  ToolingRow,
  FeedbackPayload,
} from "./types";

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function call<T = unknown>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const reqInit: RequestInit = {
    ...rest,
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : init.body,
  };
  const res = await fetch(`${BASE}${path}`, reqInit);
  const ctype = res.headers.get("content-type") ?? "";
  const isJson = ctype.includes("application/json");
  const payload = isJson ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const msg = isJson && payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail: unknown }).detail)
      : `HTTP ${res.status}`;
    throw new ApiError(res.status, payload, msg);
  }
  return payload as T;
}

// ---------------------------------------------------------------------------
// SSE — analyze stream
// ---------------------------------------------------------------------------

export interface AnalyzeStreamBody {
  analysis_id?:              string;
  step_url:                  string;
  drawing_url:               string;
  file_name:                 string;
  user_id?:                  string | null;
  batch_size?:               number;
  forced_assembly_part_type?: string | null;
}

export interface SSEEvent {
  event: string;
  /** Parsed JSON; falls back to the raw string if parse fails. */
  data:  unknown;
  raw:   string;
}

/** Split an SSE buffer into events + remaining unterminated text. */
export function parseSSEBuffer(buffer: string): { events: SSEEvent[]; remaining: string } {
  const events: SSEEvent[] = [];
  const parts = buffer.split("\n\n");
  const remaining = parts.pop() ?? "";
  for (const block of parts) {
    if (!block.trim()) continue;
    let event = "message";
    let raw = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7).trim();
      else if (line.startsWith("data: ")) raw = line.slice(6);
    }
    if (!raw) continue;
    let data: unknown = raw;
    try { data = JSON.parse(raw); } catch { /* keep raw */ }
    events.push({ event, data, raw });
  }
  return { events, remaining };
}

/**
 * Open the analyze SSE stream and invoke ``onEvent`` for every frame.
 * Returns the underlying ``AbortController`` so callers can cancel.
 */
export async function analyzeStream(
  body: AnalyzeStreamBody,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/analyze-stream`, {
    method:  "POST",
    headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
    body:    JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    // Mirror the REST `call<T>` error parsing so SSE error frames carry the
    // same `{detail: ...}` extraction. FastAPI emits JSON 422/4xx error
    // bodies even on the SSE path before the stream opens.
    const ctype = res.headers.get("content-type") ?? "";
    const isJson = ctype.includes("application/json");
    const payload = isJson
      ? await res.json().catch(() => null)
      : await res.text().catch(() => "");
    const detail = isJson && payload && typeof payload === "object" && "detail" in payload
      ? String((payload as { detail: unknown }).detail)
      : `analyze-stream failed: ${res.status}`;
    throw new ApiError(res.status, payload, detail);
  }
  const reader  = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, remaining } = parseSSEBuffer(buffer);
    buffer = remaining;
    for (const ev of events) onEvent(ev);
  }
  if (buffer.trim()) {
    const { events } = parseSSEBuffer(buffer + "\n\n");
    for (const ev of events) onEvent(ev);
  }
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const health = () => call<HealthResponse>("/health");

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export interface ListAnalysesOpts {
  limit?:  number;
  offset?: number;
}

export const listAnalyses = (opts: ListAnalysesOpts = {}) => {
  const qs = new URLSearchParams();
  if (opts.limit  != null) qs.set("limit",  String(opts.limit));
  if (opts.offset != null) qs.set("offset", String(opts.offset));
  const tail = qs.toString();
  return call<AnalysisListResponse>(`/analyses${tail ? `?${tail}` : ""}`);
};

export const getAnalysis    = (id: string) => call<FinalAnswer | Record<string, unknown>>(`/analyses/${encodeURIComponent(id)}`);
export const deleteAnalysis = (id: string) => call<{ ok: boolean; removed: string[] }>(
  `/analyses/${encodeURIComponent(id)}`,
  { method: "DELETE" },
);

/** Inline corrections to a saved run. `part_info` updates the Part Information
 *  fields; `components` carries per-row BoM display overrides (one delta per
 *  component_index). Persisted to the DB — reloading reflects the edits. */
export interface AnalysisPatchBody {
  part_info?: Partial<Record<"part_number" | "revision" | "description" | "material" | "dimension_unit", string>>;
  components?: { component_index: number; overrides: Record<string, string> }[];
}
export const patchAnalysis = (id: string, body: AnalysisPatchBody) =>
  call<{ ok: boolean }>(`/analyses/${encodeURIComponent(id)}`, { method: "PATCH", json: body });

// ---------------------------------------------------------------------------
// Catalog: machines
// ---------------------------------------------------------------------------

export const listMachines   = (opts: { activeOnly?: boolean } = {}) =>
  call<MachineRow[]>(`/catalog/machines${opts.activeOnly ? "?active=true" : ""}`);

export const createMachine  = (body: MachineCreate) =>
  call<MachineRow>(`/catalog/machines`, { method: "POST", json: body });

export const updateMachine  = (id: string, patch: Partial<MachineRow>) =>
  call<MachineRow>(`/catalog/machines/${encodeURIComponent(id)}`, { method: "PATCH", json: patch });

export const deleteMachine  = (id: string, opts: { hard?: boolean } = {}) =>
  call<{ ok: boolean; hard: boolean; rows_affected: number }>(
    `/catalog/machines/${encodeURIComponent(id)}${opts.hard ? "?hard=true" : ""}`,
    { method: "DELETE" },
  );

// ---------------------------------------------------------------------------
// Catalog: tooling
// ---------------------------------------------------------------------------

export const listTooling    = (opts: { activeOnly?: boolean } = {}) =>
  call<ToolingRow[]>(`/catalog/tooling${opts.activeOnly ? "?active=true" : ""}`);

export const createTooling  = (body: ToolingCreate) =>
  call<ToolingRow>(`/catalog/tooling`, { method: "POST", json: body });

export const updateTooling  = (id: string, patch: Partial<ToolingRow>) =>
  call<ToolingRow>(`/catalog/tooling/${encodeURIComponent(id)}`, { method: "PATCH", json: patch });

export const deleteTooling  = (id: string, opts: { hard?: boolean } = {}) =>
  call<{ ok: boolean; hard: boolean; rows_affected: number }>(
    `/catalog/tooling/${encodeURIComponent(id)}${opts.hard ? "?hard=true" : ""}`,
    { method: "DELETE" },
  );

// ---------------------------------------------------------------------------
// Catalog: labor rates
// ---------------------------------------------------------------------------

export const listLaborRates   = (opts: { activeOnly?: boolean } = {}) =>
  call<LaborRateRow[]>(`/catalog/labor-rates${opts.activeOnly ? "?active=true" : ""}`);

export const createLaborRate  = (body: LaborRateCreate) =>
  call<LaborRateRow>(`/catalog/labor-rates`, { method: "POST", json: body });

export const updateLaborRate  = (id: string, patch: Partial<LaborRateRow>) =>
  call<LaborRateRow>(`/catalog/labor-rates/${encodeURIComponent(id)}`, { method: "PATCH", json: patch });

export const deleteLaborRate  = (id: string, opts: { hard?: boolean } = {}) =>
  call<{ ok: boolean; hard: boolean; rows_affected: number }>(
    `/catalog/labor-rates/${encodeURIComponent(id)}${opts.hard ? "?hard=true" : ""}`,
    { method: "DELETE" },
  );

// ---------------------------------------------------------------------------
// Catalog: material stock
// ---------------------------------------------------------------------------

export const listMaterialStock   = (opts: { activeOnly?: boolean } = {}) =>
  call<MaterialStockRow[]>(`/catalog/material-stock${opts.activeOnly ? "?active=true" : ""}`);

export const createMaterialStock = (body: MaterialStockCreate) =>
  call<MaterialStockRow>(`/catalog/material-stock`, { method: "POST", json: body });

export const updateMaterialStock = (id: string, patch: Partial<MaterialStockRow>) =>
  call<MaterialStockRow>(`/catalog/material-stock/${encodeURIComponent(id)}`, { method: "PATCH", json: patch });

export const deleteMaterialStock = (id: string, opts: { hard?: boolean } = {}) =>
  call<{ ok: boolean; hard: boolean; rows_affected: number }>(
    `/catalog/material-stock/${encodeURIComponent(id)}${opts.hard ? "?hard=true" : ""}`,
    { method: "DELETE" },
  );

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export const sendFeedback = (body: FeedbackPayload) =>
  call<{ ok: boolean; written?: boolean }>(`/feedback`, { method: "POST", json: body });

// ---------------------------------------------------------------------------
// Convenience namespace
// ---------------------------------------------------------------------------

export const api = {
  health,
  analyzeStream,
  // history
  listAnalyses, getAnalysis, deleteAnalysis, patchAnalysis,
  // catalog
  listMachines, createMachine, updateMachine, deleteMachine,
  listTooling, createTooling, updateTooling, deleteTooling,
  listLaborRates, createLaborRate, updateLaborRate, deleteLaborRate,
  listMaterialStock, createMaterialStock, updateMaterialStock, deleteMaterialStock,
  // feedback
  sendFeedback,
};

export default api;
