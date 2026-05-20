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
import {
  ArrowLeft, Plus, Pencil, Trash2, Loader2, AlertCircle, Box, Search,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import type { MaterialStockRow } from "@/lib/api/types";

type MaterialForm =
  | "plate" | "sheet" | "bar_round" | "bar_square" | "bar_hex"
  | "tube_round" | "tube_rect" | "billet" | "block";

const MATERIAL_FORMS: { value: MaterialForm; label: string }[] = [
  { value: "plate",      label: "Plate"        },
  { value: "sheet",      label: "Sheet"        },
  { value: "bar_round",  label: "Bar (Round)"  },
  { value: "bar_square", label: "Bar (Square)" },
  { value: "bar_hex",    label: "Bar (Hex)"    },
  { value: "tube_round", label: "Tube (Round)" },
  { value: "tube_rect",  label: "Tube (Rect)"  },
  { value: "billet",     label: "Billet"       },
  { value: "block",      label: "Block"        },
];

/** Row shape augmented with the flat dimension columns + extra metadata the
 *  form uses (server stores them via Pydantic ``extra="allow"``). */
interface MaterialStockExt extends MaterialStockRow {
  length_mm?:            number | null;
  width_mm?:             number | null;
  height_mm?:            number | null;
  diameter_mm?:          number | null;
  thickness_mm?:         number | null;
  wall_thickness_mm?:    number | null;
  lead_time_days?:       number | null;
  recommended_sfm?:      number | null;
  machinability_rating?: number | null;
  density_g_per_cm3?:    number | null;
  notes?:                string | null;
}

type DimKey = "length_mm" | "width_mm" | "height_mm" | "diameter_mm" | "thickness_mm" | "wall_thickness_mm";

const DIM_KEYS: { key: DimKey; label: string }[] = [
  { key: "length_mm",         label: "Length"    },
  { key: "width_mm",          label: "Width"     },
  { key: "height_mm",         label: "Height"    },
  { key: "diameter_mm",       label: "Diameter"  },
  { key: "thickness_mm",      label: "Thickness" },
  { key: "wall_thickness_mm", label: "Wall"      },
];

function formatStockDims(row: MaterialStockExt): string {
  const parts: string[] = [];
  if (row.length_mm         != null) parts.push(`L${row.length_mm}`);
  if (row.width_mm          != null) parts.push(`W${row.width_mm}`);
  if (row.height_mm         != null) parts.push(`H${row.height_mm}`);
  if (row.diameter_mm       != null) parts.push(`Ø${row.diameter_mm}`);
  if (row.thickness_mm      != null) parts.push(`t${row.thickness_mm}`);
  if (row.wall_thickness_mm != null) parts.push(`w${row.wall_thickness_mm}`);
  return parts.length > 0 ? parts.join(" × ") : "—";
}

interface StockForm {
  material_name:        string;
  material_form:        MaterialForm | null;
  length_mm:            number | null;
  width_mm:             number | null;
  height_mm:            number | null;
  diameter_mm:          number | null;
  thickness_mm:         number | null;
  wall_thickness_mm:    number | null;
  cost_per_stock_usd:   number | null;
  lead_time_days:       number | null;
  supplier:             string | null;
  recommended_sfm:      number | null;
  machinability_rating: number | null;
  density_g_per_cm3:    number | null;
  notes:                string | null;
  is_active:            boolean;
}

const EMPTY_FORM: StockForm = {
  material_name:        "",
  material_form:        "plate",
  length_mm:            null,
  width_mm:             null,
  height_mm:            null,
  diameter_mm:          null,
  thickness_mm:         null,
  wall_thickness_mm:    null,
  cost_per_stock_usd:   null,
  lead_time_days:       null,
  supplier:             null,
  recommended_sfm:      null,
  machinability_rating: null,
  density_g_per_cm3:    null,
  notes:                null,
  is_active:            true,
};

export default function MaterialStockPage() {
  const [rows,         setRows]        = useState<MaterialStockExt[]>([]);
  const [loading,      setLoading]     = useState(true);
  const [error,        setError]       = useState<string | null>(null);
  const [search,       setSearch]      = useState("");
  const [formFilter,   setFormFilter]  = useState<MaterialForm | "">("");
  const [showDialog,   setShowDialog]  = useState(false);
  const [editRow,      setEditRow]     = useState<MaterialStockExt | null>(null);
  const [formData,     setFormData]    = useState<StockForm>({ ...EMPTY_FORM });
  const [saving,       setSaving]      = useState(false);
  const [deleting,     setDeleting]    = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listMaterialStock();
      setRows((data as MaterialStockExt[]) ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load material stock");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openAdd = () => {
    setEditRow(null);
    setFormData({ ...EMPTY_FORM });
    setShowDialog(true);
  };

  const openEdit = (row: MaterialStockExt) => {
    setEditRow(row);
    setFormData({
      material_name:        row.material_name,
      material_form:        (row.material_form as MaterialForm | undefined) ?? null,
      length_mm:            row.length_mm ?? null,
      width_mm:             row.width_mm ?? null,
      height_mm:            row.height_mm ?? null,
      diameter_mm:          row.diameter_mm ?? null,
      thickness_mm:         row.thickness_mm ?? null,
      wall_thickness_mm:    row.wall_thickness_mm ?? null,
      cost_per_stock_usd:   row.cost_per_stock_usd ?? null,
      lead_time_days:       row.lead_time_days ?? null,
      supplier:             row.supplier ?? null,
      recommended_sfm:      row.recommended_sfm ?? null,
      machinability_rating: row.machinability_rating ?? null,
      density_g_per_cm3:    row.density_g_per_cm3 ?? null,
      notes:                row.notes ?? null,
      is_active:            row.is_active ?? true,
    });
    setShowDialog(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editRow) await api.updateMaterialStock(editRow.id, formData);
      else         await api.createMaterialStock(formData);
      setShowDialog(false);
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
      await api.deleteMaterialStock(id, { hard: true });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  };

  const handleToggle = async (row: MaterialStockExt) => {
    setError(null);
    try {
      await api.updateMaterialStock(row.id, { is_active: !row.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Toggle failed");
    }
  };

  const filtered = rows.filter((r) => {
    const matchSearch = !search || r.material_name.toLowerCase().includes(search.toLowerCase());
    const matchForm   = !formFilter || r.material_form === formFilter;
    return matchSearch && matchForm;
  });

  const setNumberOrNull = (key: keyof StockForm) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = parseFloat(e.target.value);
    setFormData((p) => ({ ...p, [key]: Number.isFinite(n) ? n : null }));
  };

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/cost-db">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="w-3.5 h-3.5" />
            Cost DB
          </Button>
        </Link>
        <div className="flex items-center gap-2 flex-1">
          <Box className="w-4.5 h-4.5 text-amber-500" />
          <h1 className="text-[18px] font-bold tracking-tight">Material Stock</h1>
          <Badge variant="secondary" className="ml-2 text-[10px] font-mono">{rows.length} items</Badge>
        </div>
        <Button
          size="sm"
          className="bg-amber-500 hover:bg-amber-600 text-white"
          onClick={openAdd}
        >
          <Plus className="w-3.5 h-3.5" />
          Add Stock
        </Button>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input
            type="text"
            placeholder="Search material…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-[13px] rounded-lg border border-slate-200 bg-white focus:outline-none focus:ring-2 focus:ring-amber-400/40"
          />
        </div>
        <select
          value={formFilter}
          onChange={(e) => setFormFilter(e.target.value as MaterialForm | "")}
          className="text-[13px] rounded-lg border border-slate-200 bg-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400/40"
        >
          <option value="">All forms</option>
          {MATERIAL_FORMS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-[13px]">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <Card className="border-slate-200/60 shadow-sm overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50/80">
              <TableHead className="text-[11px] uppercase tracking-wider">Material</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Form</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Dimensions (mm)</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Cost / Stock</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Lead (days)</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Active</TableHead>
              <TableHead className="text-[11px] uppercase tracking-wider">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 7 }).map((__, j) => (
                    <TableCell key={j}><Skeleton className="h-4 w-full" /></TableCell>
                  ))}
                </TableRow>
              ))
            ) : filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-sm text-slate-400">
                  {rows.length === 0 ? "No stock items yet. Click \"Add Stock\" to begin." : "No results match your filter."}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((row) => (
                <TableRow key={row.id} className={cn(!row.is_active && "opacity-50")}>
                  <TableCell className="font-medium text-[13px]">{row.material_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[10px] font-mono border-amber-200 text-amber-700 bg-amber-50">
                      {MATERIAL_FORMS.find((f) => f.value === row.material_form)?.label ?? row.material_form ?? "—"}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-[12px] text-slate-500">{formatStockDims(row)}</TableCell>
                  <TableCell className="font-mono text-[13px]">{row.cost_per_stock_usd != null ? `$${row.cost_per_stock_usd.toFixed(2)}` : "—"}</TableCell>
                  <TableCell className="font-mono text-[13px] text-slate-500">{row.lead_time_days ?? "—"}</TableCell>
                  <TableCell>
                    <button
                      onClick={() => handleToggle(row)}
                      aria-label={row.is_active ? "Deactivate" : "Activate"}
                      className={cn(
                        "relative w-9 h-5 rounded-full transition-colors",
                        row.is_active ? "bg-amber-500" : "bg-slate-200",
                      )}
                    >
                      <span className={cn(
                        "absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                        row.is_active ? "translate-x-4" : "translate-x-0",
                      )} />
                    </button>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => openEdit(row)}>
                        <Pencil className="w-3 h-3" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-red-500 hover:text-red-600 hover:bg-red-50"
                        onClick={() => handleDelete(row.id)}
                        disabled={deleting === row.id}
                      >
                        {deleting === row.id
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <Trash2 className="w-3 h-3" />
                        }
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      {showDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl w-full max-w-lg space-y-5 p-6 max-h-[90vh] overflow-y-auto">
            <h2 className="text-[16px] font-bold">{editRow ? "Edit Stock" : "Add Stock Item"}</h2>

            <div className="space-y-3.5">
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Material Name</label>
                <input
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                  value={formData.material_name}
                  onChange={(e) => setFormData((p) => ({ ...p, material_name: e.target.value }))}
                  placeholder="e.g. AL6061-T6"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Form</label>
                <select
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                  value={formData.material_form ?? ""}
                  onChange={(e) => setFormData((p) => ({ ...p, material_form: (e.target.value || null) as MaterialForm | null }))}
                >
                  <option value="">—</option>
                  {MATERIAL_FORMS.map((f) => (
                    <option key={f.value} value={f.value}>{f.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Dimensions (mm) <span className="font-normal normal-case text-slate-400">— fill what applies to this form</span></label>
                <div className="grid grid-cols-3 gap-2">
                  {DIM_KEYS.map(({ key, label }) => (
                    <div key={key}>
                      <div className="text-[10px] text-slate-400 mb-0.5">{label}</div>
                      <input
                        type="number"
                        min={0}
                        step={0.1}
                        className="w-full rounded-lg border border-slate-200 px-2.5 py-1.5 text-[12.5px] font-mono focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                        value={(formData[key] as number | null) ?? ""}
                        onChange={setNumberOrNull(key)}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Cost per Stock (USD)</label>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                    value={formData.cost_per_stock_usd ?? ""}
                    onChange={setNumberOrNull("cost_per_stock_usd")}
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Lead Time (days)</label>
                  <input
                    type="number"
                    min={0}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                    value={formData.lead_time_days ?? ""}
                    onChange={setNumberOrNull("lead_time_days")}
                    placeholder="Optional"
                  />
                </div>
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Supplier</label>
                <input
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-amber-400/40"
                  value={formData.supplier ?? ""}
                  onChange={(e) => setFormData((p) => ({ ...p, supplier: e.target.value || null }))}
                  placeholder="Optional"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">SFM</label>
                  <input
                    type="number" min={0}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                    value={formData.recommended_sfm ?? ""}
                    onChange={setNumberOrNull("recommended_sfm")}
                    placeholder="surface ft/min"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Machinability</label>
                  <input
                    type="number" min={0} max={100}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                    value={formData.machinability_rating ?? ""}
                    onChange={setNumberOrNull("machinability_rating")}
                    placeholder="0-100"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Density</label>
                  <input
                    type="number" min={0} step={0.01}
                    className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[13px] font-mono"
                    value={formData.density_g_per_cm3 ?? ""}
                    onChange={setNumberOrNull("density_g_per_cm3")}
                    placeholder="g/cm³"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowDialog(false)}>Cancel</Button>
              <Button
                size="sm"
                className="bg-amber-500 hover:bg-amber-600 text-white"
                onClick={handleSave}
                disabled={saving || !formData.material_name}
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : null}
                {editRow ? "Save Changes" : "Add Item"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
