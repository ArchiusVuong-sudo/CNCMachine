"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown, Brain } from "lucide-react";

interface ThinkingPanelProps {
  content: string;
  isLive?: boolean;
  iteration?: number;
  label?: string;
}

export function ThinkingPanel({ content, isLive, iteration, label = "Model Thinking" }: ThinkingPanelProps) {
  const [open, setOpen] = useState(true);
  const [raw, setRaw]   = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isLive && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [content, isLive]);

  const segments = useMemo(() => parseSegments(content), [content]);

  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/6 overflow-hidden min-w-0 max-w-full">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-amber-500/8 transition-colors"
      >
        <Brain className="w-3.5 h-3.5 text-amber-400/80 shrink-0" />
        <span className="flex-1 text-left text-[12px] font-medium text-amber-300/70">
          {label}
          {iteration && <span className="text-amber-500/50 ml-2">Step {iteration}</span>}
        </span>
        {isLive && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />}
        <ChevronDown className={cn("w-3.5 h-3.5 text-amber-500/40 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="border-t border-amber-500/10">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-amber-500/10 text-[10px] text-amber-400/60">
            <span>{segments.length} segment{segments.length === 1 ? "" : "s"}</span>
            <button
              onClick={() => setRaw((v) => !v)}
              className="px-1.5 py-0.5 rounded hover:bg-amber-500/10 text-amber-400/80"
            >
              {raw ? "show readable" : "show raw"}
            </button>
          </div>
          <div
            ref={ref}
            className="px-3 py-2.5 text-[11px] leading-relaxed max-h-56 overflow-y-auto overflow-x-hidden text-muted-foreground/70 min-w-0 max-w-full space-y-2"
          >
            {raw ? (
              <pre className="font-mono whitespace-pre-wrap [overflow-wrap:anywhere]">
                {content}
                {isLive && <span className="animate-pulse text-amber-400">▋</span>}
              </pre>
            ) : (
              <>
                {segments.map((seg, i) => (
                  <ThinkingSegment key={i} seg={seg} />
                ))}
                {isLive && <span className="animate-pulse text-amber-400">▋</span>}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Thinking content comes through as an interleaved stream of free-form
// reasoning text + JSON object chunks. Walk the buffer, peel off JSON objects
// where possible, leave the rest as plain text.
// ───────────────────────────────────────────────────────────────────────────

type Segment =
  | { kind: "text"; text: string }
  | { kind: "json"; value: unknown; pretty: string };

function parseSegments(content: string): Segment[] {
  if (!content) return [];
  const out: Segment[] = [];
  let i = 0;
  let textBuf = "";

  const flushText = () => {
    const trimmed = textBuf.replace(/^\s+|\s+$/g, "");
    if (trimmed) out.push({ kind: "text", text: trimmed });
    textBuf = "";
  };

  while (i < content.length) {
    const ch = content[i];
    if (ch === "{") {
      const end = findMatchingBrace(content, i);
      if (end > i) {
        const candidate = content.slice(i, end + 1);
        try {
          const parsed = JSON.parse(candidate);
          flushText();
          out.push({
            kind:   "json",
            value:  parsed,
            pretty: JSON.stringify(parsed, null, 2),
          });
          i = end + 1;
          continue;
        } catch {
          // not valid JSON — fall through to text
        }
      }
    }
    textBuf += ch;
    i += 1;
  }
  flushText();
  return out;
}

function findMatchingBrace(s: string, start: number): number {
  let depth   = 0;
  let inStr   = false;
  let escape  = false;
  for (let i = start; i < s.length; i++) {
    const ch = s[i];
    if (inStr) {
      if (escape)           { escape = false; }
      else if (ch === "\\") { escape = true;  }
      else if (ch === '"')  { inStr = false;  }
      continue;
    }
    if (ch === '"') { inStr = true;  continue; }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return -1;
}

function ThinkingSegment({ seg }: { seg: Segment }) {
  if (seg.kind === "text") {
    return (
      <div className="whitespace-pre-wrap [overflow-wrap:anywhere] font-sans text-foreground/70">
        {seg.text}
      </div>
    );
  }
  return <JsonSummary value={seg.value} pretty={seg.pretty} />;
}

function JsonSummary({ value, pretty }: { value: unknown; pretty: string }) {
  const rows = summarizeJson(value);
  return (
    <details className="rounded border border-amber-500/15 bg-amber-500/5 px-2 py-1.5">
      <summary className="text-[10px] uppercase tracking-wider font-semibold text-amber-400/70 cursor-pointer">
        Structured chunk · {rows.length} field{rows.length === 1 ? "" : "s"}
      </summary>
      {rows.length > 0 ? (
        <dl className="mt-1.5 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-[11px]">
          {rows.map(([k, v], i) => (
            <div key={i} className="contents">
              <dt className="text-amber-300/70 font-medium">{k}</dt>
              <dd className="text-foreground/80 font-mono truncate" title={v}>{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <pre className="text-[10.5px] font-mono mt-1.5 whitespace-pre-wrap [overflow-wrap:anywhere]">
          {pretty}
        </pre>
      )}
    </details>
  );
}

function summarizeJson(value: unknown, prefix = "", out: [string, string][] = []): [string, string][] {
  if (value === null || value === undefined) {
    if (prefix) out.push([prefix, "—"]);
    return out;
  }
  if (typeof value !== "object") {
    out.push([prefix || "value", String(value)]);
    return out;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      out.push([prefix || "items", "empty list"]);
      return out;
    }
    // For arrays of primitives, render as joined list. For arrays of objects,
    // just summarize length to keep the panel readable.
    const allPrim = value.every((v) => v === null || typeof v !== "object");
    if (allPrim) {
      out.push([prefix || "items", value.map((v) => String(v)).join(", ")]);
    } else {
      out.push([prefix || "items", `${value.length} item${value.length === 1 ? "" : "s"}`]);
    }
    return out;
  }
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      summarizeJson(v, path, out);
    } else {
      summarizeJson(v, path, out);
    }
  }
  return out;
}
