"use client";

import { useEffect, useState } from "react";
import { Box, FileImage } from "lucide-react";
import { cn } from "@/lib/utils";
import { StepViewer } from "./step-viewer";
import { DrawingViewer } from "./drawing-viewer";

export type ViewportMode = "3d" | "2d";

export interface ViewportComponentInfo {
  component_index: number;
  name?: string | null;
  bbox?: { length_mm?: number; width_mm?: number; height_mm?: number } | null;
}

interface ViewportProps {
  stepUrl?: string | null;
  drawingUrl?: string | null;
  drawingType?: string | null;
  fileName?: string | null;
  className?: string;
  components?: ViewportComponentInfo[];
  /** "Deep" selection — drives full isolation + tab filter + cost panel.
   *  Set by clicking a row in the BoM table. */
  selectedIndex?: number | null;
  /** "Soft" selection — drives a blue tint on a single mesh WITHOUT
   *  isolating the assembly. Set by clicking a mesh in the 3D viewer,
   *  cleared when a BoM row is clicked. */
  hoveredIndex?: number | null;
  /** Called when the user clicks a 3D mesh — the parent wires this to
   *  `setHoveredIndex` so the click reads as a spot-identification gesture,
   *  not a full navigation. Clicking empty space passes `null`. */
  onSelectComponent?: (componentIndex: number | null) => void;
  /** Extraction counts shown as a compact overlay inside the 3D viewer
   *  when a component is selected. Kept as a simple shape so the heavy
   *  detail tables stay in the side panel. */
  selectedCounts?: { tolerances: number; gdt: number; threads: number } | null;
}

/**
 * Two-up part viewport with a segmented 3D / 2D switch. Only the active
 * viewer is mounted: the STEP viewer holds a WebGL context and the PDF
 * viewer a worker, so unmounting the inactive one frees those resources and
 * the active viewer reloads cleanly when re-selected.
 */
export function Viewport({ stepUrl, drawingUrl, drawingType, fileName, className, components, selectedIndex, hoveredIndex, onSelectComponent, selectedCounts }: ViewportProps) {
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
          ? <StepViewer fileUrl={stepUrl ?? null} title={fileName ?? undefined} components={components} selectedIndex={selectedIndex} hoveredIndex={hoveredIndex} onSelectComponent={onSelectComponent} selectedCounts={selectedCounts} />
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
