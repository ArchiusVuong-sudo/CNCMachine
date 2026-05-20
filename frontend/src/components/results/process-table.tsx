"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface Process {
  id: string;
  label: string;
  operation: string;
  tool?: { type?: string; diameter?: number | null; material?: string } | null;
  params?: { spindle_rpm?: number | null; feed_rate_ipm?: number | null } | null;
  toolpath_distance_in?: number | null;
}

export function ProcessTable({ processes }: { processes: Process[] }) {
  if (!processes.length) return null;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Operation</TableHead>
          <TableHead>Tool</TableHead>
          <TableHead className="text-right">RPM</TableHead>
          <TableHead className="text-right">Feed (IPM)</TableHead>
          <TableHead className="text-right">Distance (in)</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {processes.map((p) => (
          <TableRow key={p.id}>
            <TableCell className="text-sm">{p.label}</TableCell>
            <TableCell>
              {p.tool ? (
                <div className="flex items-center gap-1.5">
                  {p.tool.material && <Badge variant="outline" className="text-[10px]">{p.tool.material}</Badge>}
                  <span className="text-xs text-muted-foreground">
                    {p.tool.diameter != null ? `${p.tool.diameter.toFixed(3)}" ` : ""}{p.tool.type ?? "—"}
                  </span>
                </div>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell className="text-right font-mono text-xs">{p.params?.spindle_rpm ?? "—"}</TableCell>
            <TableCell className="text-right font-mono text-xs">{p.params?.feed_rate_ipm != null ? p.params.feed_rate_ipm.toFixed(1) : "—"}</TableCell>
            <TableCell className="text-right font-mono text-xs">{p.toolpath_distance_in != null ? p.toolpath_distance_in.toFixed(3) : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
