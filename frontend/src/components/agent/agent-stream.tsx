"use client";

import { useRef, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { ToolExecution } from "./tool-execution";
import { ThinkingPanel } from "./thinking-panel";
import {
  Bot,
  CheckCircle2,
  AlertCircle,
  Loader2,
  XCircle,
  Sparkles,
} from "lucide-react";

export interface AgentStreamMessage {
  id: string;
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

interface AgentStreamProps {
  messages: AgentStreamMessage[];
  liveThinking: string;
  isStreaming: boolean;
}

export function AgentStream({ messages, liveThinking, isStreaming }: AgentStreamProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const viewport = wrapperRef.current?.querySelector<HTMLDivElement>(
      "[data-radix-scroll-area-viewport]"
    );
    if (!viewport) return;
    const nearBottom =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 80;
    if (nearBottom) {
      viewport.scrollTop = viewport.scrollHeight;
    }
  }, [messages, liveThinking]);

  return (
    <div ref={wrapperRef} className="h-full">
      <ScrollArea className="h-full">
        <div className="space-y-3 p-4 min-w-0 max-w-full">
          {messages.map((msg) => (
            <AgentMessage key={msg.id} msg={msg} />
          ))}

          {liveThinking && <ThinkingPanel content={liveThinking} isLive label="Vision Analysis — Reading Drawing" />}

          {isStreaming && !liveThinking && messages.length > 0 && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground/60 py-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Processing...</span>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

function AgentMessage({ msg }: { msg: AgentStreamMessage }) {
  const { type, data } = msg;

  switch (type) {
    case "agent_start":
      return (
        <div className="flex items-start gap-3 rounded-lg bg-primary/8 border border-primary/20 p-3">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-primary/15 mt-0.5 shrink-0">
            <Sparkles className="w-3.5 h-3.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-semibold text-primary/90">Analysis Started</div>
            <div className="text-[11px] text-primary/50 mt-0.5 break-words">
              {data.message as string}
            </div>
          </div>
        </div>
      );

    case "status": {
      const d = data as { step?: number; title?: string; message?: string; completed?: boolean; failed?: boolean };
      return (
        <div className="flex items-start gap-2 text-sm text-muted-foreground pl-1 min-w-0">
          <div className="shrink-0 mt-0.5">
            {d.failed ? (
              <XCircle className="w-3.5 h-3.5 text-destructive" />
            ) : d.completed ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
            )}
          </div>
          <div className="flex-1 min-w-0 flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium text-foreground/80 break-words">{d.title}</span>
            {d.message && (
              <span className="text-muted-foreground/60 break-words">{d.message}</span>
            )}
          </div>
        </div>
      );
    }

    case "thinking":
      return <ThinkingPanel content={data.content as string} iteration={data.iteration as number} />;

    case "tool_call":
      return (
        <ToolExecution
          tool={data.tool as string}
          args={data.args as Record<string, unknown>}
          status="running"
          componentIndex={data.component_index as number | undefined}
        />
      );

    case "tool_result":
      return (
        <ToolExecution
          tool={data.tool as string}
          result={data.result as Record<string, unknown>}
          duration={data.duration_ms as number}
          status={(data.result as Record<string, unknown>)?.error ? "error" : "complete"}
          componentIndex={data.component_index as number | undefined}
        />
      );

    case "agent_message":
      return (
        <div className="flex items-start gap-3 rounded-lg bg-card border border-border p-3">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-muted mt-0.5 shrink-0">
            <Bot className="w-3.5 h-3.5 text-muted-foreground" />
          </div>
          <div className="flex-1 min-w-0 text-[13px] text-muted-foreground whitespace-pre-wrap break-words leading-relaxed">
            {data.content as string}
          </div>
        </div>
      );

    case "final_answer": {
      // Totals are already shown in the prominent summary cards beside the
      // activity feed — just mark the completion here without re-printing them.
      return (
        <div className="flex items-start gap-3 rounded-lg bg-emerald-500/8 border border-emerald-500/25 p-3">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-emerald-500/15 mt-0.5 shrink-0">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-semibold text-emerald-600">Analysis Complete</div>
            {data.summary ? (
              <div className="text-[11.5px] text-emerald-600/70 whitespace-pre-wrap leading-relaxed mt-0.5">
                {data.summary as string}
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    case "done": {
      const d = data as { elapsed_seconds?: number };
      return (
        <div className="flex items-center justify-center gap-3 border-t border-border mt-1 py-2.5 font-mono text-[11px] text-muted-foreground/60">
          <span>Finished in {(d.elapsed_seconds ?? 0).toFixed(1)}s</span>
        </div>
      );
    }

    case "error":
      return (
        <div className="flex items-start gap-3 rounded-lg bg-red-500/8 border border-red-500/20 p-3">
          <AlertCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
          <div className="text-[12px] text-red-400">
            {data.message as string}
          </div>
        </div>
      );

    case "save_ok": {
      const stats = (data.stats as Record<string, number | boolean> | undefined) ?? {};
      const parts: string[] = [];
      if (stats.extraction_saved)             parts.push("2D extraction");
      if ((stats.components_saved as number)) parts.push(`${stats.components_saved} comp`);
      if ((stats.features_saved   as number)) parts.push(`${stats.features_saved} feat`);
      if ((stats.processes_saved  as number)) parts.push(`${stats.processes_saved} proc`);
      if ((stats.gcode_saved      as number)) parts.push(`${stats.gcode_saved} gcode`);
      return (
        <div className="flex items-center gap-2 text-[11.5px] text-emerald-600/80 pl-1 py-1">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
          <span>Saved to database · {parts.join(", ") || "top-level only"}</span>
        </div>
      );
    }

    case "save_warning": {
      const msg = (data.message as string) ?? "Save result reported issues";
      const errs = (data.errors as { scope: string; message: string }[] | undefined) ?? [];
      return (
        <div className="flex items-start gap-3 rounded-lg bg-amber-500/8 border border-amber-500/25 p-3">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-semibold text-amber-700">Database save issue</div>
            <div className="text-[11.5px] text-amber-600/80 mt-0.5 leading-relaxed">{msg}</div>
            {errs.length > 1 && (
              <div className="mt-1.5 text-[10.5px] text-amber-600/60 font-mono space-y-0.5">
                {errs.slice(0, 5).map((e, i) => (
                  <div key={i} className="truncate">· {e.scope}: {e.message}</div>
                ))}
                {errs.length > 5 && <div>… and {errs.length - 5} more</div>}
              </div>
            )}
          </div>
        </div>
      );
    }

    case "warning": {
      // kb_engine emits these for silent fallbacks (BOM mapping crash,
      // per-component pipeline failure, etc.) so the user has a chance to
      // see why downstream rows look wrong. Fields: stage, code, message,
      // optionally component_index + details.
      const msg     = (data.message as string) ?? "Pipeline reported a non-fatal warning";
      const stage   = data.stage as string | undefined;
      const code    = data.code  as string | undefined;
      const compIdx = data.component_index as number | undefined;
      return (
        <div className="flex items-start gap-3 rounded-lg bg-amber-500/8 border border-amber-500/25 p-3">
          <AlertCircle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-[12px] font-semibold text-amber-700">
                Pipeline warning
              </div>
              {stage && (
                <span className="text-[10px] font-mono text-amber-700/80 bg-amber-100/60 border border-amber-300/40 rounded px-1.5 py-0.5">
                  {stage}
                </span>
              )}
              {compIdx != null && (
                <span className="text-[10px] font-mono text-amber-700/80 bg-amber-100/60 border border-amber-300/40 rounded px-1.5 py-0.5">
                  component {compIdx}
                </span>
              )}
              {code && (
                <span className="text-[10px] font-mono text-amber-600/70">
                  {code}
                </span>
              )}
            </div>
            <div className="text-[11.5px] text-amber-600/80 mt-0.5 leading-relaxed">{msg}</div>
          </div>
        </div>
      );
    }

    default:
      return null;
  }
}
