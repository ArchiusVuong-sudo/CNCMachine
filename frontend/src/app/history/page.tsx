"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowRight,
  Trash2,
  FileBox,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { AnalysisSummary } from "@/lib/api/types";

const PAGE_SIZE = 10;

export default function HistoryPage() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const fetchAnalyses = useCallback(async (silent = false, pageOverride?: number) => {
    if (!silent) setLoading(true);
    try {
      const p = pageOverride ?? page;
      const offset = (p - 1) * PAGE_SIZE;
      const res = await api.listAnalyses({ limit: PAGE_SIZE, offset });
      setAnalyses(res.data ?? []);
      setTotal(typeof res.total === "number" ? res.total : 0);
    } catch (e) {
      console.error("Failed to fetch analyses:", e);
    }
    if (!silent) setLoading(false);
  }, [page]);

  useEffect(() => {
    fetchAnalyses();
  }, [fetchAnalyses]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const handleDelete = async (id: string) => {
    try {
      await api.deleteAnalysis(id);
      await fetchAnalyses(true);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      console.error("Delete failed:", msg);
      alert(`Delete failed: ${msg}`);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Analysis History</h1>
          <p className="text-muted-foreground text-sm mt-1">
            View and manage your previous CNC costing analyses.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => fetchAnalyses()}
          className="gap-2"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-6 space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-4">
                  <Skeleton className="h-4 w-4 rounded" />
                  <Skeleton className="h-4 flex-1" />
                  <Skeleton className="h-4 w-20" />
                  <Skeleton className="h-4 w-16" />
                </div>
              ))}
            </div>
          ) : analyses.length === 0 ? (
            <div className="py-16 text-center">
              <FileBox className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">No analyses yet.</p>
              <Link href="/analyze">
                <Button variant="outline" size="sm" className="mt-3">
                  Start New Analysis
                </Button>
              </Link>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-border hover:bg-transparent">
                  <TableHead className="text-muted-foreground/70">File</TableHead>
                  <TableHead className="text-muted-foreground/70">Assembly</TableHead>
                  <TableHead className="text-right text-muted-foreground/70">Components</TableHead>
                  <TableHead className="text-right text-muted-foreground/70">Cycle Time</TableHead>
                  <TableHead className="text-right text-muted-foreground/70">Cost</TableHead>
                  <TableHead className="text-right text-muted-foreground/70">Date</TableHead>
                  <TableHead className="w-28" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {analyses.map((a) => (
                  <TableRow key={a.id} className="border-border">
                    <TableCell className="max-w-[260px]">
                      <div
                        className="text-sm font-medium truncate text-foreground/80"
                        title={a.file_name ?? a.id}
                      >
                        {a.file_name ?? <span className="text-muted-foreground/40">(unnamed)</span>}
                      </div>
                      <div className="text-[10px] font-mono text-muted-foreground/40 truncate mt-0.5" title={a.id}>
                        {a.id}
                      </div>
                    </TableCell>

                    <TableCell className="text-xs text-muted-foreground/80 max-w-[200px] truncate" title={a.assembly_name ?? ""}>
                      {a.assembly_name || <span className="text-muted-foreground/30">—</span>}
                    </TableCell>

                    <TableCell className="text-right font-mono text-xs text-muted-foreground/80">
                      {a.n_components != null ? a.n_components : <span className="text-muted-foreground/30">—</span>}
                    </TableCell>

                    <TableCell className="text-right font-mono text-xs text-muted-foreground/80">
                      {a.total_minutes != null
                        ? `${a.total_minutes.toFixed(1)} min`
                        : <span className="text-muted-foreground/30">—</span>}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs text-muted-foreground/80">
                      {a.total_usd != null
                        ? `$${a.total_usd.toFixed(2)}`
                        : <span className="text-muted-foreground/30">—</span>}
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground/60">
                      {new Date(a.created_at * 1000).toLocaleDateString()}
                    </TableCell>

                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        <Link href={`/analysis/${a.id}`}>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-foreground"
                            title="View details"
                          >
                            <ArrowRight className="w-3.5 h-3.5" />
                          </Button>
                        </Link>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={() => handleDelete(a.id)}
                          title="Delete"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {!loading && total > 0 && (
        <div className="flex items-center justify-between px-1">
          <p className="text-xs text-muted-foreground">
            Showing {(page - 1) * PAGE_SIZE + 1}
            {"–"}
            {Math.min(page * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              title="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums min-w-[68px] text-center">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-8 w-8"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              title="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
