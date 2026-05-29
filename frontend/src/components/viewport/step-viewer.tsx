"use client";

import { Box, Loader2, AlertCircle, RotateCcw, ZoomIn, ZoomOut, Scissors, ExternalLink, Scan, Ruler } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useStepViewer } from "@/lib/hooks/viewer/useStepViewer";
import type { ViewportComponentInfo } from "./viewport";

interface StepViewerProps {
  fileUrl: string | null;
  title?: string;
  components?: ViewportComponentInfo[];
  selectedIndex?: number | null;
}

type Dim = "l" | "w" | "h";

/**
 * 3D STEP viewer — presentation only. The WebGL lifecycle, orbit/zoom,
 * component isolation, bounding-box overlay, measure tool, and cross-section
 * clip live in `useStepViewer`; this component wires the hook's grouped API
 * (refs, pointer handlers, toolbar actions, overlay labels) to the DOM.
 */
export function StepViewer({ fileUrl, title, components, selectedIndex }: StepViewerProps) {
  const {
    containerRef, overlayRef, loading, error, modelLoaded, cursorStyle,
    pointer, view, measure, bbox, section,
  } = useStepViewer({ fileUrl, components, selectedIndex });

  const showPlaceholder = !fileUrl;

  return (
    <div className="relative h-full w-full">
      {modelLoaded && !loading && (
        <div className="absolute right-3 top-3 z-10 flex gap-1.5">
          {/* Measure tool */}
          <Button
            variant={measure.active ? "default" : "outline"}
            size="icon"
            className="h-8 w-8 bg-background/90 backdrop-blur-sm"
            title="Measure distance"
            onClick={measure.toggle}
          >
            <Ruler className="h-4 w-4" />
          </Button>
          {/* BBox toggle */}
          <Button
            variant={bbox.visible ? "default" : "outline"}
            size="icon"
            className="h-8 w-8 bg-background/90 backdrop-blur-sm"
            title="Bounding box dimensions"
            onClick={bbox.toggle}
          >
            <Scan className="h-4 w-4" />
          </Button>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                variant={section.enabled ? "default" : "outline"}
                size="icon"
                className="h-8 w-8 bg-background/90 backdrop-blur-sm"
                title="Cross section"
              >
                <Scissors className="h-4 w-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-52 p-3" side="bottom" align="end">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">Cross section</span>
                  <Button
                    variant={section.enabled ? "default" : "outline"}
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => section.setEnabled(!section.enabled)}
                  >
                    {section.enabled ? "On" : "Off"}
                  </Button>
                </div>
                {section.enabled && (
                  <div className="space-y-2">
                    <span className="text-xs text-muted-foreground">Cut position</span>
                    <Slider value={section.position} onValueChange={section.setPosition} min={0} max={100} step={1} />
                  </div>
                )}
              </div>
            </PopoverContent>
          </Popover>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={view.zoomIn} title="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={view.zoomOut} title="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" onClick={view.resetView} title="Reset view">
            <RotateCcw className="h-4 w-4" />
          </Button>
          {fileUrl && (
            <Button asChild variant="outline" size="icon" className="h-8 w-8 bg-background/90 backdrop-blur-sm" title="Open raw STEP">
              <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
            </Button>
          )}
        </div>
      )}

      {title && !showPlaceholder && (
        <div className="absolute left-3 top-3 z-10 rounded-md bg-background/90 px-2 py-1 text-xs text-muted-foreground backdrop-blur-sm">
          {title}
        </div>
      )}

      {/* Measure status badge */}
      {measure.active && modelLoaded && (
        <div className="absolute bottom-3 left-1/2 z-10 -translate-x-1/2 rounded-md bg-background/90 px-3 py-1.5 text-xs text-muted-foreground backdrop-blur-sm shadow">
          {measure.count === 0 && "Click a point on the model"}
          {measure.count === 1 && "Click a second point"}
          {measure.count === 2 && measure.distMm !== null && (
            <span className="font-semibold text-foreground">Dist: {measure.distMm.toFixed(1)} mm</span>
          )}
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="text-sm text-muted-foreground">Loading 3D model…</span>
          </div>
        </div>
      )}

      {error && !loading && !showPlaceholder && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 px-4 text-center backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2">
            <AlertCircle className="h-8 w-8 text-destructive" />
            <span className="text-sm text-destructive">{error}</span>
          </div>
        </div>
      )}

      {showPlaceholder && !loading && (
        <div className="viewport-grid absolute inset-0 z-20 flex flex-col items-center justify-center">
          <Box className="mb-2 h-12 w-12 text-muted-foreground/50" />
          <span className="text-sm text-muted-foreground">No CAD model available</span>
        </div>
      )}

      {/* HTML overlay for dimension labels and measure label */}
      <div ref={overlayRef} className="pointer-events-none absolute inset-0" style={{ zIndex: 15 }}>
        {bbox.visible && (["l", "w", "h"] as Dim[]).map((dim) => {
          const pos = bbox.labelPos[dim];
          if (!pos) return null;
          const label = dim.toUpperCase();
          return (
            <div
              key={dim}
              style={{
                position: "absolute",
                left: pos.x,
                top: pos.y,
                transform: "translate(-50%, -50%)",
                pointerEvents: "auto",
                zIndex: 15,
              }}
            >
              {bbox.editingDim === dim ? (
                <input
                  autoFocus
                  type="number"
                  value={bbox.editInput}
                  onChange={(e) => bbox.setEditInput(e.target.value)}
                  onBlur={bbox.onEditCommit}
                  onKeyDown={bbox.onEditKeyDown}
                  className="w-20 rounded border border-blue-400 bg-white px-1 py-0.5 text-xs font-medium text-blue-700 shadow outline-none"
                  style={{ pointerEvents: "auto" }}
                />
              ) : (
                <div
                  className="cursor-text rounded bg-blue-600/90 px-1.5 py-0.5 text-xs font-semibold text-white shadow backdrop-blur-sm select-none"
                  title="Double-click to edit"
                  onDoubleClick={() => bbox.onDoubleClick(dim)}
                >
                  {label}: {bbox.dimValues[dim].toFixed(1)} mm
                </div>
              )}
            </div>
          );
        })}
        {measure.active && measure.labelPos && measure.distMm !== null && (
          <div
            style={{
              position: "absolute",
              left: measure.labelPos.x,
              top: measure.labelPos.y,
              transform: "translate(-50%, -120%)",
              pointerEvents: "none",
              zIndex: 15,
            }}
          >
            <div className="rounded bg-red-600/90 px-2 py-0.5 text-xs font-semibold text-white shadow backdrop-blur-sm">
              Dist: {measure.distMm.toFixed(1)} mm
            </div>
          </div>
        )}
      </div>

      <div
        ref={containerRef}
        className="h-full w-full overflow-hidden"
        style={{ cursor: cursorStyle }}
        onMouseDown={pointer.onMouseDown}
        onMouseMove={pointer.onMouseMove}
        onMouseUp={pointer.onMouseUp}
        onMouseLeave={pointer.onMouseUp}
        onWheel={pointer.onWheel}
        onClick={pointer.onClick}
      />
    </div>
  );
}
