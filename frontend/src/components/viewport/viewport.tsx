"use client";

import { useEffect, useState } from "react";
import { Box, FileImage } from "lucide-react";
import { cn } from "@/lib/utils";
import { StepViewer } from "./step-viewer";
import { DrawingViewer } from "./drawing-viewer";

export type ViewportMode = "3d" | "2d";

interface ViewportProps {
  stepUrl?: string | null;
  drawingUrl?: string | null;
  drawingType?: string | null;
  fileName?: string | null;
  className?: string;
}

/**
 * Two-up part viewport with a segmented 3D / 2D switch. Only the active
 * viewer is mounted: the STEP viewer holds a WebGL context and the PDF
 * viewer a worker, so unmounting the inactive one frees those resources and
 * the active viewer reloads cleanly when re-selected.
 */
export function Viewport({ stepUrl, drawingUrl, drawingType, fileName, className }: ViewportProps) {
  const has3d = !!stepUrl;
  const has2d = !!drawingUrl;

  // Prefer 3D when present; otherwise fall back to whichever exists.
  const [mode, setMode] = useState<ViewportMode>(has3d ? "3d" : "2d");

  // Keep the active tab valid as sources arrive/clear (e.g. switching runs).
  useEffect(() => {
    if (mode === "3d" && !has3d && has2d) setMode("2d");
    if (mode === "2d" && !has2d && has3d) setMode("3d");
  }, [mode, has3d, has2d]);

  return (
    <div className={cn("relative flex h-full w-full flex-col overflow-hidden rounded-xl border border-border bg-card", className)}>
      {/* Segmented switch */}
      <div className="absolute left-1/2 top-3 z-30 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border border-border bg-background/90 p-0.5 shadow-sm backdrop-blur-sm">
        <SwitchButton
          active={mode === "3d"}
          disabled={!has3d}
          onClick={() => setMode("3d")}
          icon={<Box className="h-3.5 w-3.5" />}
          label="3D Model"
        />
        <SwitchButton
          active={mode === "2d"}
          disabled={!has2d}
          onClick={() => setMode("2d")}
          icon={<FileImage className="h-3.5 w-3.5" />}
          label="2D Drawing"
        />
      </div>

      <div className="h-full w-full">
        {mode === "3d"
          ? <StepViewer fileUrl={stepUrl ?? null} title={fileName ?? undefined} />
          : <DrawingViewer fileUrl={drawingUrl ?? null} mimeType={drawingType} title={fileName ?? undefined} />}
      </div>
    </div>
  );
}

function SwitchButton({
  active, disabled, onClick, icon, label,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        disabled && "cursor-not-allowed opacity-40 hover:bg-transparent hover:text-muted-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
