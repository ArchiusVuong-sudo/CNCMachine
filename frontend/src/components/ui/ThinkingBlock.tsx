"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown, Brain, Loader2, CheckCircle2 } from "lucide-react";

export interface ThinkingBlockProps {
  /** Accumulated reasoning text */
  thinking: string;
  /** streaming = actively receiving tokens, done = finished, idle = no content yet */
  status: "streaming" | "done" | "idle";
  /** Header label — defaults to "Reasoning" */
  label?: string;
  /** If true, collapse by default when done */
  collapseWhenDone?: boolean;
}

/**
 * ThinkingBlock — collapsible reasoning display.
 *
 * Pure UI: props in, JSX out. No data fetching.
 */
export function ThinkingBlock({
  thinking,
  status,
  label = "Reasoning",
  collapseWhenDone = false,
}: ThinkingBlockProps) {
  // Start collapsed when already done and collapseWhenDone is set,
  // so there's no flash of expanded content on initial render.
  const [open, setOpen] = useState(() => !(collapseWhenDone && status === "done"));
  const preRef = useRef<HTMLPreElement>(null);

  // Auto-scroll while streaming
  useEffect(() => {
    if (status === "streaming" && preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [thinking, status]);

  // Collapse when transitioning to done
  useEffect(() => {
    if (collapseWhenDone && status === "done") {
      setOpen(false);
    }
  }, [status, collapseWhenDone]);

  if (status === "idle" && !thinking) return null;

  return (
    <div
      className={cn(
        "rounded-lg border overflow-hidden transition-all",
        status === "streaming"
          ? "border-amber-300/40 bg-amber-50/60"
          : "border-border bg-muted/20"
      )}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors",
          status === "streaming"
            ? "hover:bg-amber-100/40"
            : "hover:bg-muted/40"
        )}
      >
        <Brain
          className={cn(
            "w-3.5 h-3.5 shrink-0",
            status === "streaming" ? "text-amber-500" : "text-muted-foreground/50"
          )}
        />

        <span
          className={cn(
            "flex-1 text-left text-[12px] font-semibold tracking-wide",
            status === "streaming" ? "text-amber-700" : "text-muted-foreground/70"
          )}
        >
          {label}
        </span>

        {/* Status indicator */}
        {status === "streaming" && (
          <span className="flex items-center gap-1.5 text-[10px] font-mono text-amber-600/70">
            <Loader2 className="w-3 h-3 animate-spin" />
            thinking…
          </span>
        )}
        {status === "done" && (
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500/70 shrink-0" />
        )}

        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 shrink-0 transition-transform",
            open ? "rotate-180" : "",
            status === "streaming" ? "text-amber-400/60" : "text-muted-foreground/30"
          )}
        />
      </button>

      {/* Body */}
      {open && (
        <pre
          ref={preRef}
          className={cn(
            "px-4 py-3 text-[11px] leading-relaxed font-mono whitespace-pre-wrap",
            "max-h-52 overflow-y-auto border-t",
            status === "streaming"
              ? "text-amber-900/70 border-amber-200/40 bg-amber-50/30"
              : "text-muted-foreground/60 border-border bg-background/60"
          )}
        >
          {thinking || " "}
          {status === "streaming" && (
            <span className="animate-pulse text-amber-500">▋</span>
          )}
        </pre>
      )}
    </div>
  );
}
