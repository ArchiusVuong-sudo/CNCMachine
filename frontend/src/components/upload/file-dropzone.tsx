"use client";

import { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { cn } from "@/lib/utils";
import { Upload, FileBox, FileImage, X, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";

const MAX_SIZE_3D = 200 * 1024 * 1024;  // 200 MB — STEP files can be large
const MAX_SIZE_2D = 50  * 1024 * 1024;  // 50 MB

interface FileDropzoneProps {
  label: string;
  description: string;
  accept: Record<string, string[]>;
  file: File | null;
  onFileSelect: (file: File | null) => void;
  icon: "3d" | "2d";
  required?: boolean;
  maxSizeBytes?: number;
  /** Inline error message — shown with red border below the dropzone */
  error?: string;
  /** Called with a human-readable rejection reason when a file is rejected */
  onReject?: (reason: string) => void;
}

export function FileDropzone({
  label, description, accept, file, onFileSelect, icon,
  maxSizeBytes, error, onReject,
}: FileDropzoneProps) {
  const limit = maxSizeBytes ?? (icon === "3d" ? MAX_SIZE_3D : MAX_SIZE_2D);

  const onDrop = useCallback(
    (accepted: File[], rejected: { file: File; errors: readonly { code: string; message: string }[] }[]) => {
      if (accepted.length > 0) {
        const f = accepted[0];
        if (f.size > limit) {
          onReject?.(`${f.name} is too large (max ${Math.round(limit / 1024 / 1024)} MB).`);
          return;
        }
        onFileSelect(f);
      } else if (rejected.length > 0) {
        const code = rejected[0].errors[0]?.code;
        if (code === "file-too-large") {
          onReject?.(`File is too large (max ${Math.round(limit / 1024 / 1024)} MB).`);
        } else {
          // Derive accepted extensions from the accept map
          const exts = Object.values(accept).flat().join(", ");
          onReject?.(`Invalid file type. Accepted: ${exts}`);
        }
      }
    },
    [accept, limit, onFileSelect, onReject]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    multiple: false,
    maxSize: limit,
  });

  const Icon = icon === "3d" ? FileBox : FileImage;

  if (file) {
    return (
      <div className="space-y-1.5">
        <div className="relative flex items-center gap-3.5 rounded-xl border border-primary/25 bg-primary/4 p-4 shadow-[0_1px_3px_0_rgb(0,0,0,0.05)]">
          <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/12 shrink-0">
            <CheckCircle2 className="w-4.5 h-4.5 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-semibold truncate text-foreground">{file.name}</div>
            <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
              {file.size > 1024 * 1024
                ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
                : `${(file.size / 1024).toFixed(1)} KB`}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
            onClick={(e) => { e.stopPropagation(); onFileSelect(null); }}
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        </div>
        {error && (
          <p className="text-[11.5px] text-red-600 font-medium px-1">{error}</p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div
        {...getRootProps()}
        className={cn(
          "flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-10 cursor-pointer transition-all",
          error
            ? "border-red-300 bg-red-50/50"
            : isDragActive
            ? "border-primary/50 bg-primary/5 shadow-[0_0_0_4px_oklch(0.60_0.175_68/0.08)]"
            : "border-border bg-card hover:border-primary/30 hover:bg-muted/20"
        )}
      >
        <input {...getInputProps()} />
        <div className={cn(
          "flex items-center justify-center w-12 h-12 rounded-2xl transition-colors",
          error ? "bg-red-100" : isDragActive ? "bg-primary/15" : "bg-muted/70"
        )}>
          {isDragActive
            ? <Upload className="w-5 h-5 text-primary" />
            : <Icon className={cn("w-5 h-5", error ? "text-red-400" : "text-muted-foreground/50")} />
          }
        </div>
        <div className="text-center space-y-1">
          <div className="text-[13.5px] font-semibold text-foreground/80">{label}</div>
          <div className="text-[11.5px] text-muted-foreground/70">{description}</div>
        </div>
      </div>
      {error && (
        <p className="text-[11.5px] text-red-600 font-medium px-1">{error}</p>
      )}
    </div>
  );
}
