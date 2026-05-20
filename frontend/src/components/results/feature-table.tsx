"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface Feature {
  id: string;
  mfg_type?: string;
  type?: string;
  description: string;
  quantity: number;
  tolerance_class?: string;
  geometry?: Record<string, number>;
}

const TOL_VARIANT: Record<string, "destructive" | "warning" | "info" | "secondary"> = {
  precision: "destructive",
  close: "warning",
  medium: "info",
  general: "secondary",
};

export function FeatureTable({ features }: { features: Feature[] }) {
  if (!features.length) return null;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">ID</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Description</TableHead>
          <TableHead className="w-12 text-center">Qty</TableHead>
          <TableHead className="w-24">Tolerance</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {features.map((f) => (
          <TableRow key={f.id}>
            <TableCell className="font-mono text-xs">{f.id}</TableCell>
            <TableCell>
              <Badge variant="outline" className="font-mono text-[10px]">
                {f.mfg_type || f.type}
              </Badge>
            </TableCell>
            <TableCell className="text-sm">{f.description}</TableCell>
            <TableCell className="text-center">{f.quantity}</TableCell>
            <TableCell>
              <Badge variant={TOL_VARIANT[f.tolerance_class || "general"] || "secondary"} className="text-[10px]">
                {f.tolerance_class || "general"}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
