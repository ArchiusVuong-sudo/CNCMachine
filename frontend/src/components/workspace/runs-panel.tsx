"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Plus, Search, Trash2, PanelLeftClose, PanelLeft, Loader2, Database,
  FileBox, RefreshCw, AlertCircle, ChevronLeft, ChevronRight,
} from "lucide-react";
import type { AnalysisSummary } from "@/lib/api/types";
import { listAnalyses, deleteAnalysis } from "@/lib/api/client";
import { BrandMark } from "@/components/layout/brand-mark";
import { Button } from "@/components/ui/button";
import { usd, dateShort } from "@/lib/format";
import { cn } from "@/lib/utils";

interface RunsPanelProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** Analysis id currently shown in the workspace (highlighted in the list). */
  activeId: string | null;
  onSelectRun: (id: string) => void;
  onNewEstimate: () => void;
  /** A synthetic entry for the in-flight live run (not yet in history). */
  liveRun?: { id: string; label: string; streaming: boolean } | null;
  /** Bump to force a re-fetch (e.g. after a run finishes). */
  refreshSignal?: number;
}

/** Projects per page in the expanded listing before pagination kicks in. */
const PAGE_SIZE = 8;

/** Row title — Part Number + Revision when known, else the file name. */
function runTitle(r: AnalysisSummary): string {
  if (r.part_number) return r.revision ? `${r.part_number}  ·  Rev ${r.revision}` : r.part_number;
  return r.file_name || r.assembly_name || r.id;
}

/** Secondary line — total estimated cost · material · date created. */
function runSubtitle(r: AnalysisSummary): string {
  return [
    r.total_usd != null ? usd(r.total_usd) : null,
    r.material || null,
    dateShort(r.created_at),
  ].filter(Boolean).join("  ·  ");
}

export function RunsPanel({
  collapsed, onToggleCollapse, activeId, onSelectRun, onNewEstimate, liveRun, refreshSignal,
}: RunsPanelProps) {
  const [runs, setRuns]       = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [query, setQuery]     = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [page, setPage]       = useState(0);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await listAnalyses({ limit: 200 });
      setRuns(resp.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchRuns(); }, [fetchRuns, refreshSignal]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(id);
    try {
      await deleteAnalysis(id);
      setRuns((prev) => prev.filter((r) => r.id !== id));
    } catch {
      /* leave the row; surfaced via list refresh */
    } finally {
      setDeleting(null);
    }
  };

  // Newest first, then apply the search filter.
  const filtered = useMemo(() => {
    const sorted = [...runs].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0));
    const q = query.trim().toLowerCase();
    if (!q) return sorted;
    return sorted.filter((r) => {
      const hay = `${r.part_number ?? ""} ${r.revision ?? ""} ${r.material ?? ""} ${r.file_name ?? ""} ${r.assembly_name ?? ""} ${r.id}`.toLowerCase();
      return hay.includes(q);
    });
  }, [runs, query]);

  // Reset to the first page whenever the result set changes underneath us.
  useEffect(() => { setPage(0); }, [query, refreshSignal]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage  = Math.min(page, pageCount - 1);
  const pageRows  = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  // ── Collapsed rail ───────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="flex h-full w-14 shrink-0 flex-col items-center gap-2 border-r border-sidebar-border bg-sidebar py-3">
        <button
          onClick={onToggleCollapse}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Expand panel"
        >
          <PanelLeft className="h-4.5 w-4.5" />
        </button>
        <Button
          size="icon"
          className="h-9 w-9 rounded-lg"
          onClick={onNewEstimate}
          title="New Project"
        >
          <Plus className="h-4.5 w-4.5" />
        </Button>
        <div className="mt-1 flex flex-1 flex-col items-center gap-1.5 overflow-hidden">
          {liveRun?.streaming && (
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10" title={liveRun.label}>
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
            </span>
          )}
          {filtered.slice(0, 12).map((r) => (
            <button
              key={r.id}
              onClick={() => onSelectRun(r.id)}
              title={runTitle(r)}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                activeId === r.id && "bg-primary/10 text-primary",
              )}
            >
              <FileBox className="h-4 w-4" />
            </button>
          ))}
        </div>
        <Link
          href="/cost-db"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Cost database"
        >
          <Database className="h-4.5 w-4.5" />
        </Link>
      </aside>
    );
  }

  // ── Expanded panel ─────────────────────────────────────────────────────────
  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      {/* Header */}
      <div className="flex items-start justify-between px-3 py-3">
        <BrandMark />
        <button
          onClick={onToggleCollapse}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          title="Collapse panel"
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>

      {/* New Project */}
      <div className="px-3 pb-2">
        <Button className="w-full gap-1.5" onClick={onNewEstimate}>
          <Plus className="h-4 w-4" />
          New Project
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search projects…"
            className="h-9 w-full rounded-lg border border-input bg-background pl-8 pr-3 text-sm outline-none transition-shadow placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
          />
        </div>
      </div>

      {/* List */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <div className="flex items-center justify-between px-1.5 py-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Previous projects
          </span>
          <button
            onClick={() => void fetchRuns()}
            className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            title="Refresh"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </button>
        </div>

        {/* Live run (not yet persisted to history) */}
        {liveRun?.streaming && (
          <RunRow
            active={activeId === liveRun.id}
            onClick={() => onSelectRun(liveRun.id)}
            title={liveRun.label}
            subtitle="Running…"
            streaming
          />
        )}

        {loading && runs.length === 0 ? (
          <div className="flex items-center gap-2 px-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading projects…
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 px-2 py-4 text-[13px] text-red-600">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div>{error}</div>
              <button onClick={() => void fetchRuns()} className="mt-1 font-medium underline">Retry</button>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="px-2 py-8 text-center text-[13px] text-muted-foreground">
            {query ? "No projects match your search." : "No projects yet. Start a new project."}
          </div>
        ) : (
          <div className="space-y-0.5">
            {pageRows.map((r) => (
              <RunRow
                key={r.id}
                active={activeId === r.id}
                onClick={() => onSelectRun(r.id)}
                onDelete={(e) => handleDelete(r.id, e)}
                deleting={deleting === r.id}
                title={runTitle(r)}
                subtitle={runSubtitle(r)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-2 border-t border-sidebar-border px-3 py-2 text-[12px] text-muted-foreground">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
            className="flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-accent hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
            title="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="tabular-nums">Page {safePage + 1} of {pageCount}</span>
          <button
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={safePage >= pageCount - 1}
            className="flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-accent hover:text-foreground disabled:opacity-30 disabled:hover:bg-transparent"
            title="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Footer */}
      <div className="border-t border-sidebar-border p-2">
        <Link
          href="/cost-db"
          className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <Database className="h-4 w-4" />
          Cost database
        </Link>
      </div>
    </aside>
  );
}

function RunRow({
  active, onClick, onDelete, deleting, title, subtitle, streaming,
}: {
  active: boolean;
  onClick: () => void;
  onDelete?: (e: React.MouseEvent) => void;
  deleting?: boolean;
  title: string;
  subtitle: string;
  streaming?: boolean;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "group flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 transition-colors",
        active ? "bg-primary/10" : "hover:bg-accent",
      )}
    >
      <span className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
        active ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
      )}>
        {streaming ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : <FileBox className="h-4 w-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <div className={cn("truncate text-[13px] font-medium", active ? "text-primary" : "text-foreground")}>
          {title}
        </div>
        <div className="truncate text-[11px] text-muted-foreground">{subtitle}</div>
      </div>
      {onDelete && (
        <button
          onClick={onDelete}
          disabled={deleting}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
          title="Delete project"
        >
          {deleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
        </button>
      )}
    </div>
  );
}
