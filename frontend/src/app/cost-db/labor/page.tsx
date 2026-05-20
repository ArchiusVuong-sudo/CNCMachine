"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ArrowLeft, Plus, Pencil, Trash2, Loader2, AlertCircle, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import type { LaborRateRow } from "@/lib/api/types";

type LaborRole =
  | "machinist" | "programmer" | "inspector" | "setup_technician"
  | "deburrer"  | "assembler"  | "welder";

const ROLE_OPTIONS: { value: LaborRole; label: string }[] = [
  { value: "machinist",        label: "Machinist"         },
  { value: "programmer",       label: "CNC Programmer"    },
  { value: "inspector",        label: "Inspector"         },
  { value: "setup_technician", label: "Setup Technician"  },
  { value: "deburrer",         label: "Deburrer"          },
  { value: "assembler",        label: "Assembler"         },
  { value: "welder",           label: "Welder"            },
];

/** Row shape augmented with the optional ``notes`` column the form uses. */
interface LaborRateExt extends LaborRateRow {
  notes?: string | null;
}

interface LaborForm {
  role_name:       LaborRole;
  hourly_rate_usd: number;
  is_active:       boolean;
  notes:           string | null;
}

const EMPTY: LaborForm = {
  role_name:       "machinist",
  hourly_rate_usd: 60,
  is_active:       true,
  notes:           null,
};

export default function LaborRatesPage() {
  const [rows,     setRows]    = useState<LaborRateExt[]>([]);
  const [loading,  setLoading] = useState(true);
  const [error,    setError]   = useState<string | null>(null);
  const [showDlg,  setShowDlg] = useState(false);
  const [editRow,  setEditRow] = useState<LaborRateExt | null>(null);
  const [form,     setForm]    = useState<LaborForm>({ ...EMPTY });
  const [saving,   setSaving]  = useState(false);
  const [deleting, setDeleting]= useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listLaborRates();
      setRows((data as LaborRateExt[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load labor rates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openAdd  = () => { setEditRow(null);  setForm({ ...EMPTY }); setShowDlg(true); };
  const openEdit = (r: LaborRateExt) => {
    setEditRow(r);
    setForm({
      role_name:       (r.role_name as LaborRole) ?? "machinist",
      hourly_rate_usd: r.hourly_rate_usd ?? 0,
      is_active:       r.is_active ?? true,
      notes:           r.notes ?? null,
    });
    setShowDlg(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editRow) await api.updateLaborRate(editRow.id, form);
      else         await api.createLaborRate(form);
      setShowDlg(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    setDeleting(id);
    setError(null);
    try {
      await api.deleteLaborRate(id, { hard: true });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const handleToggle = async (r: LaborRateExt) => {
    setError(null);
    try {
      await api.updateLaborRate(r.id, { is_active: !r.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const labelFor = (role: string) => ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role;

  return (
    <div className="max-w-3xl mx-auto py-8 px-4 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/cost-db"><Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground"><ArrowLeft className="w-3.5 h-3.5" />Cost DB</Button></Link>
        <div className="flex items-center gap-2 flex-1">
          <Users className="w-4.5 h-4.5 text-purple-500" />
          <h1 className="text-[18px] font-bold tracking-tight">Labor Rates</h1>
          <Badge variant="secondary" className="ml-2 text-[10px] font-mono">{rows.length} roles</Badge>
        </div>
        <Button size="sm" className="bg-purple-500 hover:bg-purple-600 text-white" onClick={openAdd}>
          <Plus className="w-3.5 h-3.5" />Add Role
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-[13px]">
          <AlertCircle className="w-4 h-4 shrink-0" />{error}
        </div>
      )}

      <Card className="border-slate-200/60 shadow-sm overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50/80">
              <TableHead className="text-[11px] uppercase tracking-wider">Role</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">$/hr</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Notes</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Active</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>{Array.from({ length: 5 }).map((__, j) => <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>)}</TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center py-10 text-sm text-slate-400">No labor rates yet.</TableCell></TableRow>
            ) : rows.map((r) => (
              <TableRow key={r.id} className={cn(!r.is_active && "opacity-50")}>
                <TableCell className="font-medium text-[13px]">{labelFor(r.role_name)}</TableCell>
                <TableCell className="font-mono text-[13px] font-semibold text-purple-700">${r.hourly_rate_usd}/hr</TableCell>
                <TableCell className="text-[12px] text-slate-400 max-w-[200px] truncate">{r.notes ?? "—"}</TableCell>
                <TableCell>
                  <button onClick={() => handleToggle(r)} aria-label="Toggle active"
                    className={cn("relative w-9 h-5 rounded-full transition-colors", r.is_active ? "bg-purple-500" : "bg-slate-200")}>
                    <span className={cn("absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform", r.is_active ? "translate-x-4" : "translate-x-0")} />
                  </button>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => openEdit(r)}><Pencil className="w-3 h-3" /></Button>
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-red-500 hover:bg-red-50" onClick={() => handleDelete(r.id)} disabled={deleting === r.id}>
                      {deleting === r.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {showDlg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl border shadow-2xl w-full max-w-sm p-6 space-y-4">
            <h2 className="text-[16px] font-bold">{editRow ? "Edit Labor Rate" : "Add Labor Rate"}</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Role</label>
                <select className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-purple-400/40"
                  value={form.role_name}
                  onChange={(e) => setForm((p) => ({ ...p, role_name: e.target.value as LaborRole }))}>
                  {ROLE_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Rate (USD/hr)</label>
                <input type="number" min={0} step={0.5} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-2 focus:ring-purple-400/40" value={form.hourly_rate_usd} onChange={(e) => setForm((p) => ({ ...p, hourly_rate_usd: parseFloat(e.target.value) || 0 }))} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Notes</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-purple-400/40" value={form.notes ?? ""} onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value || null }))} placeholder="Optional" />
              </div>
            </div>
            <div className="flex justify-end gap-2.5 pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowDlg(false)}>Cancel</Button>
              <Button size="sm" className="bg-purple-500 hover:bg-purple-600 text-white" onClick={handleSave} disabled={saving || !form.role_name}>
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}
                {editRow ? "Save" : "Add"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
