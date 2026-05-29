"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, ChevronDown } from "lucide-react";
import type { AgentStreamMessage } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ProgressTimeline } from "./progress-timeline";
import { cn } from "@/lib/utils";

/**
 * The live engine-by-engine progress feed. Stays mounted after the run
 * finishes (the SSE hook keeps `messages`), but auto-collapses once results
 * arrive so the cost estimate sits front-and-center. Click the header to
 * re-expand and review what each engine did — and a manual toggle is never
 * overridden by the lifecycle.
 */
export function PipelineActivityCard({
  messages, liveThinking, isStreaming, collapsed,
}: {
  messages: AgentStreamMessage[];
  liveThinking: string;
  isStreaming: boolean;
  collapsed: boolean;
}) {
  const [open, setOpen] = useState(!collapsed);

  // React only to lifecycle *transitions* (live → done) so a user's manual
  // expand/collapse persists between renders.
  const prevCollapsed = useRef(collapsed);
  useEffect(() => {
    if (collapsed !== prevCollapsed.current) {
      setOpen(!collapsed);
      prevCollapsed.current = collapsed;
    }
  }, [collapsed]);

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-xl border border-border bg-card"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-xl px-4 py-2.5 text-left transition-colors hover:bg-muted/40">
        <Activity className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">Pipeline activity</span>
        {isStreaming && (
          <Badge variant="info" className="ml-1 text-[10px]">Live</Badge>
        )}
        <ChevronDown
          className={cn(
            "ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="max-h-105 overflow-y-auto border-t border-border p-3">
          <ProgressTimeline messages={messages} liveThinking={liveThinking} isStreaming={isStreaming} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
