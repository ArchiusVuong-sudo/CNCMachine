"use client";

import { useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { FileDropzone } from "@/components/upload/file-dropzone";
import { cn } from "@/lib/utils";

const PART_CATEGORIES: { value: string; label: string }[] = [
  { value: "",                  label: "Auto-detect (use 3D classifier)" },
  { value: "cnc_milling",       label: "CNC Milling" },
  { value: "cnc_lathe",         label: "CNC Lathe" },
  { value: "cnc_lathe_milling", label: "CNC Turn-mill" },
];

const BATCH_PRESETS = [1, 10, 50, 100, 500];

const ACCEPT_3D = {
  "application/step":  [".step", ".stp"],
  "application/STEP":  [".step", ".stp"],
  "model/step":        [".step", ".stp"],
  "application/octet-stream": [".step", ".stp"],
};
const ACCEPT_2D = {
  "application/pdf":  [".pdf"],
  "image/png":        [".png"],
  "image/jpeg":       [".jpg", ".jpeg"],
  "image/tiff":       [".tif", ".tiff"],
};

interface NewEstimateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fired when the user confirms — kicks off the SSE pipeline. */
  onRun: (file3d: File, file2d: File, batch: number, assemblyPartType: string | null) => void;
  /** True while an upload is in flight (disables the submit button). */
  busy?: boolean;
}

export function NewEstimateDialog({ open, onOpenChange, onRun, busy }: NewEstimateDialogProps) {
  const [file3d, setFile3d]   = useState<File | null>(null);
  const [file2d, setFile2d]   = useState<File | null>(null);
  const [err3d, setErr3d]     = useState<string | null>(null);
  const [err2d, setErr2d]     = useState<string | null>(null);
  const [batch, setBatch]     = useState<number>(1);
  const [partType, setPartType] = useState<string>("");
  const [formError, setFormError] = useState<string | null>(null);

  const reset = () => {
    setFile3d(null); setFile2d(null);
    setErr3d(null); setErr2d(null);
    setFormError(null);
  };

  const handleSubmit = () => {
    if (!file3d) { setFormError("A 3D STEP/STP file is required."); return; }
    if (!file2d) { setFormError("A 2D engineering drawing is required."); return; }
    setFormError(null);
    onRun(file3d, file2d, batch, partType || null);
    reset();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => { if (!busy) { onOpenChange(o); if (!o) reset(); } }}
    >
      <DialogContent className="max-w-xl gap-5">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="brand-gradient flex h-7 w-7 items-center justify-center rounded-md">
              <Bot className="h-4 w-4 text-white" />
            </span>
            New Project
          </DialogTitle>
          <DialogDescription>
            Upload 3D model (.step / .stp) file and its 2D engineering drawing for cost
            estimation. Both 3D model and 2D drawing are required.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <FileDropzone
              label="3D Model"
              description="STEP / STP · up to 200 MB"
              accept={ACCEPT_3D}
              file={file3d}
              onFileSelect={(f) => { setErr3d(null); setFile3d(f); }}
              onReject={setErr3d}
              error={err3d ?? undefined}
              icon="3d"
            />
            <FileDropzone
              label="2D Drawing"
              description="PDF, PNG, JPG, TIFF · up to 50 MB"
              accept={ACCEPT_2D}
              file={file2d}
              onFileSelect={(f) => { setErr2d(null); setFile2d(f); }}
              onReject={setErr2d}
              error={err2d ?? undefined}
              icon="2d"
            />
          </div>

          {/* Part category override */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Part category
              <span className="ml-1.5 font-normal normal-case text-muted-foreground/60">(override the auto-classifier)</span>
            </label>
            <select
              value={partType}
              onChange={(e) => setPartType(e.target.value)}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-shadow focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
            >
              {PART_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>

          {/* Batch size */}
          <div className="space-y-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Batch size
              <span className="ml-1.5 font-normal normal-case text-muted-foreground/60">(pieces per production run)</span>
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min={1}
                max={10000}
                value={batch}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!isNaN(v) && v >= 1) setBatch(v);
                }}
                className="w-24 rounded-lg border border-input bg-background px-3 py-1.5 text-sm font-mono outline-none transition-shadow focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40"
              />
              <div className="flex gap-1.5">
                {BATCH_PRESETS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setBatch(n)}
                    className={cn(
                      "rounded-md border px-2.5 py-1 font-mono text-[11px] transition-colors",
                      batch === n
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border text-muted-foreground hover:bg-muted",
                    )}
                  >
                    ×{n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {formError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5 text-[13px] text-red-700">
              {formError}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={busy || !file3d || !file2d} className="gap-1.5">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
            {busy ? "Uploading…" : "Start estimate"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
