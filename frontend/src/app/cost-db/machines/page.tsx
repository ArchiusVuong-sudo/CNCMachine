"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ArrowLeft, Plus, Pencil, Trash2, Loader2, AlertCircle, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import type { MachineRow } from "@/lib/api/types";

type MachineType =
  | "3_axis_mill" | "4_axis_mill" | "5_axis_mill"
  | "turning" | "mill_turn" | "lathe"
  | "wire_edm" | "sinker_edm" | "router";

const MACHINE_TYPES: { value: MachineType; label: string }[] = [
  { value: "3_axis_mill", label: "3-Axis Mill"  },
  { value: "4_axis_mill", label: "4-Axis Mill"  },
  { value: "5_axis_mill", label: "5-Axis Mill"  },
  { value: "turning",     label: "Turning"      },
  { value: "mill_turn",   label: "Mill-Turn"    },
  { value: "lathe",       label: "Lathe"        },
  { value: "wire_edm",    label: "EDM Wire"     },
  { value: "sinker_edm",  label: "EDM Sinker"   },
  { value: "router",      label: "Router"       },
];

/** Row shape augmented with all the legacy shop-inventory columns
 *  (server still stores them; Pydantic ``extra="allow"`` lets them through). */
interface MachineExt extends MachineRow {
  manufacturer?:        string | null;
  machine_brand?:       string | null;
  tool_holder?:         string | null;
  tool_collet?:         string | null;
  capability?:          string | null;
  work_x_mm?:           number | null;
  work_y_mm?:           number | null;
  work_z_mm?:           number | null;
  table_size_x_mm?:     number | null;
  table_size_y_mm?:     number | null;
  max_spindle_rpm?:     number | null;
  max_feed_mm_per_min?: number | null;
  max_rapid_mm_per_min?: number;
  tool_change_time_sec?: number;
}

interface MachineForm {
  machine_name:         string;
  machine_type:         MachineType | null;
  manufacturer:         string | null;
  model:                string | null;
  work_x_mm:            number | null;
  work_y_mm:            number | null;
  work_z_mm:            number | null;
  max_spindle_rpm:      number | null;
  max_feed_mm_per_min:  number | null;
  max_rapid_mm_per_min: number;
  tool_change_time_sec: number;
  hourly_rate_usd:      number;
  notes:                string | null;
  machine_brand:        string | null;
  tool_holder:          string | null;
  tool_collet:          string | null;
  capability:           string | null;
  table_size_x_mm:      number | null;
  table_size_y_mm:      number | null;
  is_active:            boolean;
}

const EMPTY_FORM: MachineForm = {
  machine_name:         "",
  machine_type:         "3_axis_mill",
  manufacturer:         null,
  model:                null,
  work_x_mm:            null,
  work_y_mm:            null,
  work_z_mm:            null,
  max_spindle_rpm:      null,
  max_feed_mm_per_min:  null,
  max_rapid_mm_per_min: 5000,
  tool_change_time_sec: 3.0,
  hourly_rate_usd:      75,
  notes:                null,
  machine_brand:        null,
  tool_holder:          null,
  tool_collet:          null,
  capability:           null,
  table_size_x_mm:      null,
  table_size_y_mm:      null,
  is_active:            true,
};

export default function MachinesPage() {
  const [rows,     setRows]     = useState<MachineExt[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [showDlg,  setShowDlg]  = useState(false);
  const [editRow,  setEditRow]  = useState<MachineExt | null>(null);
  const [form,     setForm]     = useState<MachineForm>({ ...EMPTY_FORM });
  const [saving,   setSaving]   = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listMachines();
      setRows((data as MachineExt[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load machines");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openAdd  = () => { setEditRow(null);  setForm({ ...EMPTY_FORM }); setShowDlg(true); };
  const openEdit = (r: MachineExt) => {
    setEditRow(r);
    setForm({
      machine_name:         r.machine_name,
      machine_type:         (r.machine_type as MachineType | undefined) ?? null,
      manufacturer:         r.manufacturer ?? null,
      model:                r.model ?? null,
      work_x_mm:            r.work_x_mm ?? null,
      work_y_mm:            r.work_y_mm ?? null,
      work_z_mm:            r.work_z_mm ?? null,
      max_spindle_rpm:      r.max_spindle_rpm ?? null,
      max_feed_mm_per_min:  r.max_feed_mm_per_min ?? null,
      max_rapid_mm_per_min: r.max_rapid_mm_per_min ?? 5000,
      tool_change_time_sec: r.tool_change_time_sec ?? 3.0,
      hourly_rate_usd:      r.hourly_rate_usd ?? 75,
      notes:                r.notes ?? null,
      machine_brand:        r.machine_brand ?? null,
      tool_holder:          r.tool_holder ?? null,
      tool_collet:          r.tool_collet ?? null,
      capability:           r.capability ?? null,
      table_size_x_mm:      r.table_size_x_mm ?? null,
      table_size_y_mm:      r.table_size_y_mm ?? null,
      is_active:            r.is_active ?? true,
    });
    setShowDlg(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editRow) await api.updateMachine(editRow.id, form);
      else         await api.createMachine(form);
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
      await api.deleteMachine(id, { hard: true });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const handleToggle = async (r: MachineExt) => {
    setError(null);
    try {
      await api.updateMachine(r.id, { is_active: !r.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const env = (m: MachineExt) => {
    if (m.work_x_mm != null && m.work_y_mm != null && m.work_z_mm != null) {
      return `${m.work_x_mm}×${m.work_y_mm}×${m.work_z_mm}`;
    }
    if (m.table_size_x_mm != null && m.table_size_y_mm != null) {
      return `${m.table_size_x_mm}×${m.table_size_y_mm} (table)`;
    }
    return "—";
  };

  const setField = <K extends keyof MachineForm>(key: K, value: MachineForm[K]) =>
    setForm((p) => ({ ...p, [key]: value }));

  const setNumberOrNull = <K extends keyof MachineForm>(key: K) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = parseFloat(e.target.value);
    setField(key, (Number.isFinite(n) ? n : null) as MachineForm[K]);
  };

  const setStrOrNull = <K extends keyof MachineForm>(key: K) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setField(key, ((e.target.value || null) as MachineForm[K]));
  };

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/cost-db"><Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground"><ArrowLeft className="w-3.5 h-3.5" />Cost DB</Button></Link>
        <div className="flex items-center gap-2 flex-1">
          <Settings2 className="w-4.5 h-4.5 text-indigo-500" />
          <h1 className="text-[18px] font-bold tracking-tight">Machines</h1>
          <Badge variant="secondary" className="ml-2 text-[10px] font-mono">{rows.length} items</Badge>
        </div>
        <Button size="sm" className="bg-indigo-500 hover:bg-indigo-600 text-white" onClick={openAdd}>
          <Plus className="w-3.5 h-3.5" />Add Machine
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
              <TableHead className="text-[11px] uppercase tracking-wider">Name</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Brand</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Type</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Capability</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Holder</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Envelope (mm)</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">$/hr</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Active</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>{Array.from({ length: 9 }).map((__, j) => <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>)}</TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow><TableCell colSpan={9} className="text-center py-10 text-sm text-slate-400">No machines yet.</TableCell></TableRow>
            ) : rows.map((r) => (
              <TableRow key={r.id} className={cn(!r.is_active && "opacity-50")}>
                <TableCell className="font-medium text-[13px]">{r.machine_name}</TableCell>
                <TableCell className="text-[12px] text-slate-600">{r.machine_brand ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-[10px] font-mono border-indigo-200 text-indigo-700 bg-indigo-50">
                    {MACHINE_TYPES.find((t) => t.value === r.machine_type)?.label ?? r.machine_type ?? "—"}
                  </Badge>
                </TableCell>
                <TableCell className="text-[12px] text-slate-500">{r.capability ?? "—"}</TableCell>
                <TableCell className="font-mono text-[12px] text-slate-500">{r.tool_holder ?? "—"}</TableCell>
                <TableCell className="font-mono text-[12px] text-slate-500">{env(r)}</TableCell>
                <TableCell className="font-mono text-[13px]">{r.hourly_rate_usd != null ? `$${r.hourly_rate_usd}` : "—"}</TableCell>
                <TableCell>
                  <button onClick={() => handleToggle(r)} aria-label="Toggle active"
                    className={cn("relative w-9 h-5 rounded-full transition-colors", r.is_active ? "bg-indigo-500" : "bg-slate-200")}>
                    <span className={cn("absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform", r.is_active ? "translate-x-4" : "translate-x-0")} />
                  </button>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => openEdit(r)}><Pencil className="w-3 h-3" /></Button>
                    <Button size="sm" variant="ghost" className="h-7 px-2 text-red-500 hover:text-red-600 hover:bg-red-50" onClick={() => handleDelete(r.id)} disabled={deleting === r.id}>
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
          <div className="bg-white rounded-2xl border shadow-2xl w-full max-w-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-[16px] font-bold">{editRow ? "Edit Machine" : "Add Machine"}</h2>

            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Machine Name</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-indigo-400/40"
                  value={form.machine_name}
                  onChange={(e) => setField("machine_name", e.target.value)}
                  placeholder="e.g. Haas VF-2 #1" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Brand</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.machine_brand ?? ""}
                  onChange={setStrOrNull("machine_brand")}
                  placeholder="HAAS, MAKINO, KITAMURA, …" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Type</label>
                <select className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.machine_type ?? ""}
                  onChange={(e) => setField("machine_type", (e.target.value || null) as MachineType | null)}>
                  <option value="">—</option>
                  {MACHINE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Manufacturer</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.manufacturer ?? ""}
                  onChange={setStrOrNull("manufacturer")} />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Model</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.model ?? ""}
                  onChange={setStrOrNull("model")} />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Capability</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.capability ?? ""}
                  onChange={setStrOrNull("capability")}
                  placeholder="3-axis, 4-axis, turn-mill, router, …" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Holder</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_holder ?? ""}
                  onChange={setStrOrNull("tool_holder")}
                  placeholder="HSK63F, BT30, BT40, …" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Collet</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_collet ?? ""}
                  onChange={setStrOrNull("tool_collet")}
                  placeholder="ER32, ER40, …" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Work X (mm)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.work_x_mm ?? ""}
                  onChange={setNumberOrNull("work_x_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Work Y (mm)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.work_y_mm ?? ""}
                  onChange={setNumberOrNull("work_y_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Work Z (mm)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.work_z_mm ?? ""}
                  onChange={setNumberOrNull("work_z_mm")} />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Table X (mm)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.table_size_x_mm ?? ""}
                  onChange={setNumberOrNull("table_size_x_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Table Y (mm)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.table_size_y_mm ?? ""}
                  onChange={setNumberOrNull("table_size_y_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Max RPM</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.max_spindle_rpm ?? ""}
                  onChange={setNumberOrNull("max_spindle_rpm")} />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Max Feed (mm/min)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.max_feed_mm_per_min ?? ""}
                  onChange={setNumberOrNull("max_feed_mm_per_min")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Max Rapid (mm/min)</label>
                <input type="number" className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.max_rapid_mm_per_min}
                  onChange={(e) => setField("max_rapid_mm_per_min", parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Change (sec)</label>
                <input type="number" step={0.1} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_change_time_sec}
                  onChange={(e) => setField("tool_change_time_sec", parseFloat(e.target.value) || 0)} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">$/hr</label>
                <input type="number" min={0} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.hourly_rate_usd}
                  onChange={(e) => setField("hourly_rate_usd", parseFloat(e.target.value) || 0)} />
              </div>
            </div>

            <div className="flex justify-end gap-2.5 pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowDlg(false)}>Cancel</Button>
              <Button size="sm" className="bg-indigo-500 hover:bg-indigo-600 text-white" onClick={handleSave} disabled={saving || !form.machine_name}>
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
