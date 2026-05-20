"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ArrowLeft, Plus, Pencil, Trash2, Loader2, AlertCircle, Drill } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import type { ToolingRow } from "@/lib/api/types";

type ToolType =
  | "end_mill" | "face_mill" | "drill" | "tap" | "reamer" | "boring_bar"
  | "turning_insert" | "grooving_insert" | "thread_mill" | "spot_drill"
  | "chamfer_mill" | "ball_mill" | "countersink" | "counterbore"
  | "slot_drill" | "t_slot" | "form_tool" | "radius_mill"
  | "slitting_saw" | "dovetail";
type ToolIntent   = "roughing" | "finishing" | "both";
type ToolMaterial = "HSS" | "carbide" | "ceramic" | "PCD" | "CBN" | "cobalt";

const TOOL_TYPES: { value: ToolType; label: string }[] = [
  { value: "end_mill",        label: "End Mill"      },
  { value: "face_mill",       label: "Face Mill"     },
  { value: "drill",           label: "Drill"         },
  { value: "tap",             label: "Tap"           },
  { value: "reamer",          label: "Reamer"        },
  { value: "boring_bar",      label: "Boring Bar"    },
  { value: "turning_insert",  label: "Turning Insert"},
  { value: "grooving_insert", label: "Grooving"      },
  { value: "thread_mill",     label: "Thread Mill"   },
  { value: "spot_drill",      label: "Spot Drill"    },
  { value: "chamfer_mill",    label: "Chamfer Mill"  },
  { value: "ball_mill",       label: "Ball Mill"     },
  { value: "countersink",     label: "Countersink"   },
  { value: "counterbore",     label: "Counterbore"   },
  { value: "slot_drill",      label: "Slot Drill"    },
  { value: "t_slot",          label: "T-Slot"        },
  { value: "form_tool",       label: "Form Tool"     },
  { value: "radius_mill",     label: "Radius Mill"   },
  { value: "slitting_saw",    label: "Slitting Saw"  },
  { value: "dovetail",        label: "Dovetail"      },
];

const TOOL_INTENTS: { value: ToolIntent; label: string }[] = [
  { value: "roughing",  label: "Roughing"  },
  { value: "finishing", label: "Finishing" },
  { value: "both",      label: "Both"      },
];

const TOOL_MATERIALS: { value: ToolMaterial; label: string }[] = [
  { value: "HSS",     label: "HSS"     },
  { value: "carbide", label: "Carbide" },
  { value: "ceramic", label: "Ceramic" },
  { value: "PCD",     label: "PCD"     },
  { value: "CBN",     label: "CBN"     },
  { value: "cobalt",  label: "Cobalt"  },
];

/** Row shape carrying all the legacy shop-inventory columns the form uses
 *  (server keeps them via Pydantic ``extra="allow"``). */
interface ToolingExt extends ToolingRow {
  length_mm?:                       number | null;
  corner_radius_mm?:                number | null;
  recommended_rpm_min?:             number | null;
  recommended_rpm_max?:             number | null;
  recommended_feed_min_mm_per_min?: number | null;
  recommended_feed_max_mm_per_min?: number | null;
  max_depth_of_cut_mm?:             number | null;
  machine_brand_affinity?:          string | null;
  roughing_finishing?:              ToolIntent | null;
  tool_make?:                       string | null;
  tool_holder?:                     string | null;
  tool_collet?:                     string | null;
  tool_holder_full?:                string | null;
  flute_length_mm?:                 number | null;
  tool_projection_mm?:              number | null;
  tool_length_mm?:                  number | null;
}

interface ToolForm {
  tool_name:                       string;
  tool_type:                       ToolType | null;
  diameter_mm:                     number | null;
  length_mm:                       number | null;
  flute_count:                     number | null;
  material:                        ToolMaterial | null;
  coating:                         string | null;
  corner_radius_mm:                number | null;
  recommended_rpm_min:             number | null;
  recommended_rpm_max:             number | null;
  recommended_feed_min_mm_per_min: number | null;
  recommended_feed_max_mm_per_min: number | null;
  max_depth_of_cut_mm:             number | null;
  tool_life_minutes:               number | null;
  cost_usd:                        number | null;
  notes:                           string | null;
  machine_brand_affinity:          string | null;
  roughing_finishing:              ToolIntent | null;
  tool_make:                       string | null;
  tool_holder:                     string | null;
  tool_collet:                     string | null;
  tool_holder_full:                string | null;
  flute_length_mm:                 number | null;
  tool_projection_mm:              number | null;
  tool_length_mm:                  number | null;
  tool_spec:                       string | null;
  is_active:                       boolean;
}

const EMPTY: ToolForm = {
  tool_name:                       "",
  tool_type:                       "end_mill",
  diameter_mm:                     null,
  length_mm:                       null,
  flute_count:                     null,
  material:                        null,
  coating:                         null,
  corner_radius_mm:                null,
  recommended_rpm_min:             null,
  recommended_rpm_max:             null,
  recommended_feed_min_mm_per_min: null,
  recommended_feed_max_mm_per_min: null,
  max_depth_of_cut_mm:             null,
  tool_life_minutes:               null,
  cost_usd:                        null,
  notes:                           null,
  machine_brand_affinity:          null,
  roughing_finishing:              null,
  tool_make:                       null,
  tool_holder:                     null,
  tool_collet:                     null,
  tool_holder_full:                null,
  flute_length_mm:                 null,
  tool_projection_mm:              null,
  tool_length_mm:                  null,
  tool_spec:                       null,
  is_active:                       true,
};

export default function ToolingPage() {
  const [rows,        setRows]       = useState<ToolingExt[]>([]);
  const [loading,     setLoading]    = useState(true);
  const [error,       setError]      = useState<string | null>(null);
  const [typeFilter,  setTypeFilter] = useState<ToolType | "">("");
  const [brandFilter, setBrandFilter]= useState<string>("");
  const [holderFilter,setHolderFilter]=useState<string>("");
  const [showDlg,     setShowDlg]    = useState(false);
  const [editRow,     setEditRow]    = useState<ToolingExt | null>(null);
  const [form,        setForm]       = useState<ToolForm>({ ...EMPTY });
  const [saving,      setSaving]     = useState(false);
  const [deleting,    setDeleting]   = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listTooling();
      setRows((data as ToolingExt[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tooling");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openAdd  = () => { setEditRow(null);  setForm({ ...EMPTY }); setShowDlg(true); };
  const openEdit = (r: ToolingExt) => {
    setEditRow(r);
    setForm({
      tool_name:                       r.tool_name,
      tool_type:                       (r.tool_type as ToolType | undefined) ?? null,
      diameter_mm:                     r.diameter_mm ?? null,
      length_mm:                       r.length_mm ?? null,
      flute_count:                     r.flute_count ?? null,
      material:                        (r.material as ToolMaterial | undefined) ?? null,
      coating:                         r.coating ?? null,
      corner_radius_mm:                r.corner_radius_mm ?? null,
      recommended_rpm_min:             r.recommended_rpm_min ?? null,
      recommended_rpm_max:             r.recommended_rpm_max ?? null,
      recommended_feed_min_mm_per_min: r.recommended_feed_min_mm_per_min ?? null,
      recommended_feed_max_mm_per_min: r.recommended_feed_max_mm_per_min ?? null,
      max_depth_of_cut_mm:             r.max_depth_of_cut_mm ?? null,
      tool_life_minutes:               r.tool_life_minutes ?? null,
      cost_usd:                        r.cost_usd ?? null,
      notes:                           r.notes ?? null,
      machine_brand_affinity:          r.machine_brand_affinity ?? null,
      roughing_finishing:              r.roughing_finishing ?? null,
      tool_make:                       r.tool_make ?? null,
      tool_holder:                     r.tool_holder ?? null,
      tool_collet:                     r.tool_collet ?? null,
      tool_holder_full:                r.tool_holder_full ?? null,
      flute_length_mm:                 r.flute_length_mm ?? null,
      tool_projection_mm:              r.tool_projection_mm ?? null,
      tool_length_mm:                  r.tool_length_mm ?? null,
      tool_spec:                       r.tool_spec ?? null,
      is_active:                       r.is_active ?? true,
    });
    setShowDlg(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editRow) await api.updateTooling(editRow.id, form);
      else         await api.createTooling(form);
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
      await api.deleteTooling(id, { hard: true });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const handleToggle = async (r: ToolingExt) => {
    setError(null);
    try {
      await api.updateTooling(r.id, { is_active: !r.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const brands  = Array.from(new Set(rows.map((r) => r.machine_brand_affinity).filter((b): b is string => !!b))).sort();
  const holders = Array.from(new Set(rows.map((r) => r.tool_holder).filter((h): h is string => !!h))).sort();

  const filtered = rows.filter((r) => {
    if (typeFilter   && r.tool_type              !== typeFilter)   return false;
    if (brandFilter  && r.machine_brand_affinity !== brandFilter)  return false;
    if (holderFilter && r.tool_holder            !== holderFilter) return false;
    return true;
  });

  const setField = <K extends keyof ToolForm>(key: K, value: ToolForm[K]) =>
    setForm((p) => ({ ...p, [key]: value }));

  const setNumberOrNull = <K extends keyof ToolForm>(key: K) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = parseFloat(e.target.value);
    setField(key, (Number.isFinite(n) ? n : null) as ToolForm[K]);
  };

  const setStrOrNull = <K extends keyof ToolForm>(key: K) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setField(key, ((e.target.value || null) as ToolForm[K]));
  };

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <Link href="/cost-db"><Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground"><ArrowLeft className="w-3.5 h-3.5" />Cost DB</Button></Link>
        <div className="flex items-center gap-2 flex-1">
          <Drill className="w-4.5 h-4.5 text-blue-500" />
          <h1 className="text-[18px] font-bold tracking-tight">Tooling</h1>
          <Badge variant="secondary" className="ml-2 text-[10px] font-mono">{rows.length} items</Badge>
        </div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as ToolType | "")}
          className="text-[12px] rounded-lg border border-slate-200 bg-white px-3 py-1.5">
          <option value="">All types</option>
          {TOOL_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <select value={brandFilter} onChange={(e) => setBrandFilter(e.target.value)}
          className="text-[12px] rounded-lg border border-slate-200 bg-white px-3 py-1.5">
          <option value="">All brands</option>
          {brands.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <select value={holderFilter} onChange={(e) => setHolderFilter(e.target.value)}
          className="text-[12px] rounded-lg border border-slate-200 bg-white px-3 py-1.5">
          <option value="">All holders</option>
          {holders.map((h) => <option key={h} value={h}>{h}</option>)}
        </select>
        <Button size="sm" className="bg-blue-500 hover:bg-blue-600 text-white" onClick={openAdd}>
          <Plus className="w-3.5 h-3.5" />Add Tool
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
              {["Name", "Brand", "Type", "Intent", "Holder", "Dia (mm)", "Flutes", "Cost", "Active", ""].map((h) => (
                <TableHead key={h} className="text-[11px] uppercase tracking-wider">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>{Array.from({ length: 10 }).map((__, j) => <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>)}</TableRow>
              ))
            ) : filtered.length === 0 ? (
              <TableRow><TableCell colSpan={10} className="text-center py-10 text-sm text-slate-400">No tools yet.</TableCell></TableRow>
            ) : filtered.map((r) => (
              <TableRow key={r.id} className={cn(!r.is_active && "opacity-50")}>
                <TableCell className="font-medium text-[12.5px]">{r.tool_name}</TableCell>
                <TableCell className="text-[12px] text-slate-600">{r.machine_brand_affinity ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-[9.5px] font-mono border-blue-200 text-blue-700 bg-blue-50">
                    {TOOL_TYPES.find((t) => t.value === r.tool_type)?.label ?? r.tool_type ?? "—"}
                  </Badge>
                </TableCell>
                <TableCell className="text-[11px] text-slate-500">{r.roughing_finishing ?? "—"}</TableCell>
                <TableCell className="font-mono text-[11px] text-slate-500">{r.tool_holder ?? "—"}</TableCell>
                <TableCell className="font-mono text-[12px]">{r.diameter_mm != null ? r.diameter_mm.toFixed(2) : "—"}</TableCell>
                <TableCell className="font-mono text-[12px] text-slate-500">{r.flute_count ?? "—"}</TableCell>
                <TableCell className="font-mono text-[12px]">{r.cost_usd != null ? `$${r.cost_usd.toFixed(2)}` : "—"}</TableCell>
                <TableCell>
                  <button onClick={() => handleToggle(r)} aria-label="Toggle active"
                    className={cn("relative w-9 h-5 rounded-full transition-colors", r.is_active ? "bg-blue-500" : "bg-slate-200")}>
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
          <div className="bg-white rounded-2xl border shadow-2xl w-full max-w-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-[16px] font-bold">{editRow ? "Edit Tool" : "Add Tool"}</h2>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Name</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.tool_name}
                  onChange={(e) => setField("tool_name", e.target.value)}
                  placeholder='e.g. 1/4" 4-Fl Carbide End Mill' />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Type</label>
                <select className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.tool_type ?? ""}
                  onChange={(e) => setField("tool_type", (e.target.value || null) as ToolType | null)}>
                  <option value="">—</option>
                  {TOOL_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Intent</label>
                <select className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.roughing_finishing ?? ""}
                  onChange={(e) => setField("roughing_finishing", (e.target.value || null) as ToolIntent | null)}>
                  <option value="">—</option>
                  {TOOL_INTENTS.map((i) => <option key={i.value} value={i.value}>{i.label}</option>)}
                </select>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Brand Affinity</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.machine_brand_affinity ?? ""}
                  onChange={setStrOrNull("machine_brand_affinity")}
                  placeholder="HAAS, MAKINO, Anderson, …" />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Maker</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.tool_make ?? ""}
                  onChange={setStrOrNull("tool_make")}
                  placeholder="Sandvik, Mitsubishi, OSG, …" />
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
              <div className="col-span-2">
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Holder Full Spec</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_holder_full ?? ""}
                  onChange={setStrOrNull("tool_holder_full")}
                  placeholder="e.g. HSK63F-ER32-100" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Diameter (mm)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.diameter_mm ?? ""}
                  onChange={setNumberOrNull("diameter_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Flutes</label>
                <input type="number" min={1} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.flute_count ?? ""}
                  onChange={setNumberOrNull("flute_count")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Flute Length (mm)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.flute_length_mm ?? ""}
                  onChange={setNumberOrNull("flute_length_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Length (mm)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_length_mm ?? ""}
                  onChange={setNumberOrNull("tool_length_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Projection (mm)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_projection_mm ?? ""}
                  onChange={setNumberOrNull("tool_projection_mm")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Corner Radius (mm)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.corner_radius_mm ?? ""}
                  onChange={setNumberOrNull("corner_radius_mm")} />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Material</label>
                <select className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.material ?? ""}
                  onChange={(e) => setField("material", (e.target.value || null) as ToolMaterial | null)}>
                  <option value="">—</option>
                  {TOOL_MATERIALS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Coating</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.coating ?? ""}
                  onChange={setStrOrNull("coating")}
                  placeholder="TiAlN, AlTiN, …" />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Cost (USD)</label>
                <input type="number" min={0} step={0.01} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.cost_usd ?? ""}
                  onChange={setNumberOrNull("cost_usd")} />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Life (min)</label>
                <input type="number" min={0} className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                  value={form.tool_life_minutes ?? ""}
                  onChange={setNumberOrNull("tool_life_minutes")} />
              </div>

              <div className="col-span-2">
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Tool Spec (free text)</label>
                <input className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px]"
                  value={form.tool_spec ?? ""}
                  onChange={setStrOrNull("tool_spec")}
                  placeholder="Verbatim catalogue spec" />
              </div>
            </div>

            <div className="flex justify-end gap-2.5 pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowDlg(false)}>Cancel</Button>
              <Button size="sm" className="bg-blue-500 hover:bg-blue-600 text-white" onClick={handleSave} disabled={saving || !form.tool_name}>
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
