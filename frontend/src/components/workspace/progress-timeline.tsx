"use client";

import { useEffect, useRef } from "react";
import {
  CheckCircle2, Loader2, XCircle, AlertTriangle, Wrench, Brain, Sparkles, Flag,
} from "lucide-react";
import type { AgentStreamMessage } from "@/lib/api/types";
import { cn } from "@/lib/utils";

interface ProgressTimelineProps {
  messages: AgentStreamMessage[];
  liveThinking: string;
  isStreaming: boolean;
  className?: string;
}

const TOOL_LABELS: Record<string, string> = {
  kb_read: "Read knowledge base",
  kb_find_analogues: "Find analogue parts",
  kb_query_csv: "Query parts data",
  catalog_lookup: "Look up shop catalog",
  compute_cycle_time: "Compute cycle time",
  memory_update: "Update memory",
};

export function ProgressTimeline({ messages, liveThinking, isStreaming, className }: ProgressTimelineProps) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages.length, liveThinking]);

  return (
    <div className={cn("space-y-1.5", className)}>
      {messages.map((m) => <TimelineRow key={m.id} msg={m} />)}

      {liveThinking && (
        <Row icon={<Brain className="h-3.5 w-3.5 animate-pulse text-violet-500" />} tone="thinking">
          <span className="line-clamp-2 italic text-muted-foreground">{liveThinking}</span>
        </Row>
      )}

      {isStreaming && !liveThinking && (
        <Row icon={<Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />} tone="muted">
          <span className="text-muted-foreground">Working…</span>
        </Row>
      )}
      <div ref={endRef} />
    </div>
  );
}

function TimelineRow({ msg }: { msg: AgentStreamMessage }) {
  const d = msg.data as any;

  switch (msg.type) {
    case "status": {
      const failed = !!d.failed;
      const completed = !!d.completed;
      const icon = failed
        ? <XCircle className="h-4 w-4 text-destructive" />
        : completed
          ? <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          : <Loader2 className="h-4 w-4 animate-spin text-primary" />;
      return (
        <Row icon={icon} tone="status">
          <div className="font-medium text-foreground">{d.title || "Working"}</div>
          {d.message && <div className="text-xs text-muted-foreground">{d.message}</div>}
        </Row>
      );
    }
    case "tool_call":
    case "tool_result": {
      const isResult = msg.type === "tool_result";
      const failed = !!d.failed;
      const tool = String(d.tool ?? "tool");
      const label = TOOL_LABELS[tool] ?? tool;
      const icon = failed
        ? <XCircle className="h-3.5 w-3.5 text-destructive" />
        : isResult
          ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
          : <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
      return (
        <Row icon={icon} tone="tool">
          <span className="inline-flex items-center gap-1.5">
            <Wrench className="h-3 w-3 text-muted-foreground/70" />
            <span className="text-muted-foreground">{label}</span>
            {typeof d.iteration === "number" && <span className="font-mono text-[10px] text-muted-foreground/60">#{d.iteration}</span>}
          </span>
        </Row>
      );
    }
    case "warning":
      return (
        <Row icon={<AlertTriangle className="h-3.5 w-3.5 text-amber-500" />} tone="warn">
          <span className="text-amber-700">{d.message || "Warning"}</span>
        </Row>
      );
    case "error":
      return (
        <Row icon={<XCircle className="h-4 w-4 text-destructive" />} tone="error">
          <span className="font-medium text-destructive">{d.message || "Error"}</span>
        </Row>
      );
    case "final_answer":
      return (
        <Row icon={<Sparkles className="h-4 w-4 text-primary" />} tone="status">
          <span className="font-medium text-foreground">Estimate ready</span>
        </Row>
      );
    case "done":
      return (
        <Row icon={<Flag className="h-3.5 w-3.5 text-emerald-500" />} tone="muted">
          <span className="text-muted-foreground">Pipeline complete</span>
        </Row>
      );
    default:
      return null;
  }
}

function Row({ icon, children, tone }: { icon: React.ReactNode; children: React.ReactNode; tone: string }) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-lg px-2.5 py-1.5 text-sm",
        tone === "status" && "bg-muted/40",
        tone === "error" && "bg-destructive/5",
        tone === "warn" && "bg-amber-50",
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
