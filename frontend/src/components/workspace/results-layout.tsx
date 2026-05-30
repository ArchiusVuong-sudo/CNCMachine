"use client";

import { useMemo, useState } from "react";
import type { Component, FinalAnswer } from "@/lib/api/types";
import { adoptCostedComponents, deriveResultTotals } from "@/lib/domain/results-adapter";
import { Viewport, type ViewportComponentInfo } from "@/components/viewport/viewport";
import { PartInformation } from "@/components/extraction/part-information";
import { ExtractionPanel } from "@/components/extraction/extraction-panel";
import {
  componentTolerances, componentGdt, componentThreads,
  drawingTolerances, drawingGdt, drawingThreads,
} from "@/lib/domain/extraction-model";
import { BillOfMaterial } from "@/components/results/bill-of-material";
import { CostBreakdown } from "@/components/results/cost-breakdown";
import { ManufacturingPlanCard } from "@/components/results/manufacturing-plan";
import type { ViewerSrc } from "./types";

/**
 * Estimate layout for live and history runs, per the 28 May review.
 *
 *   Row 1:  Part Information (≈30%) | 3D / 2D viewer (≈70%, A4 landscape)
 *   Row 2:  Bill of Material — full viewport width
 *   Row 3:  Cost Breakdown (≈40%) | Tolerances / GD&T / Threads (≈60%)
 *
 * Row 1 always renders (the viewer is useful while a run streams); rows 2 + 3
 * appear once components are available. Selecting a BOM row drives the viewer
 * (isolate / bbox), the cost breakdown, AND the extraction tabs (which now
 * reflect only the selected component). Drawing Notes moved into the Part
 * Information card.
 *
 * Costed-component adoption and headline totals come from `results-adapter`.
 */
export function ResultsLayout({
  results, viewer, analysisId,
}: {
  results: FinalAnswer | null;
  viewer: ViewerSrc;
  analysisId: string | null;
}) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  // 3D mesh clicks set this lighter "hovered" state — they tint the picked
  // mesh blue without isolating the rest of the assembly and without
  // changing which component the extraction tabs / cost panel are pinned
  // to.  BoM row clicks remain the only path that swaps the deep
  // `selectedIndex` (which drives isolation + tab filter).
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // BoM click = full navigation; also clears any 3D hover so the visual
  // state stays consistent.
  const selectAndClearHover = (i: number | null) => {
    setSelectedIndex(i);
    setHoveredIndex(null);
  };

  const vlm = results?.vlm_extraction ?? null;
  const components = useMemo<Component[]>(() => adoptCostedComponents(results), [results]);
  const { totalUsd, totalUsdPerLot, batchSize, confidenceBandPct, totalMin, assemblyName } = useMemo(
    () => deriveResultTotals(results, components),
    [results, components],
  );
  const hasComponents = components.length > 0;

  const viewerComponents: ViewportComponentInfo[] = components.map((c) => ({
    component_index: c.component_index,
    name: c.name,
    bbox: c.bbox
      ? { length_mm: c.bbox.length_mm, width_mm: c.bbox.width_mm, height_mm: c.bbox.height_mm }
      : null,
  }));

  // Counts for the compact overlay inside the 3D viewer. When a component
  // is picked, show that component's per-feature counts; otherwise (or when
  // the component has no tagged features yet) fall back to drawing-level.
  const selectedComp = selectedIndex == null ? null : components.find((c) => c.component_index === selectedIndex) ?? null;
  const selectedCounts = selectedComp
    ? {
        tolerances: componentTolerances(selectedComp).length,
        gdt:        componentGdt(selectedComp).length,
        threads:    componentThreads(selectedComp).length,
      }
    : vlm
      ? {
          tolerances: drawingTolerances(vlm).length,
          gdt:        drawingGdt(vlm).length,
          threads:    drawingThreads(vlm).length,
        }
      : null;

  return (
    <>
      {/* Row 1 — Part Information | Viewer
         Height capped to fit the viewport on wide screens so the BoM (Row 2)
         and Cost Breakdown (Row 3) stay reachable without large page scroll.
         Mobile/tablet (<xl): stacks, each card uses its natural / min height. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[30%_minmax(0,70%)] xl:items-stretch xl:h-[clamp(420px,calc(100vh-180px),640px)]">
        <PartInformation vlm={vlm} totalUsd={totalUsd} totalUsdPerLot={totalUsdPerLot} batchSize={batchSize} confidenceBandPct={confidenceBandPct} nComponents={hasComponents ? components.length : undefined} />
        <div className="min-h-90 min-w-0 xl:min-h-0 xl:h-full">
          <Viewport
            stepUrl={viewer.stepUrl}
            drawingUrl={viewer.drawingUrl}
            drawingType={viewer.drawingType}
            fileName={viewer.fileName}
            components={viewerComponents}
            selectedIndex={selectedIndex}
            hoveredIndex={hoveredIndex}
            onSelectComponent={setHoveredIndex}
            selectedCounts={selectedCounts}
            className="h-full w-full"
          />
        </div>
      </div>

      {hasComponents && (
        <>
          {/* Row 2 — Bill of Material (full width) */}
          <BillOfMaterial
            components={components}
            assemblyName={assemblyName}
            totalUsd={totalUsd}
            totalMin={totalMin}
            selectedIndex={selectedIndex}
            hoveredIndex={hoveredIndex}
            onSelect={selectAndClearHover}
          />

          {/* Row 3 — Cost Breakdown | Tolerances / GD&T / Threads */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,40%)_minmax(0,60%)] xl:items-stretch">
            <CostBreakdown
              analysisId={analysisId}
              components={components}
              selectedIndex={selectedIndex}
              assemblyName={assemblyName}
              totalUsd={totalUsd}
              totalMin={totalMin}
            />
            <ExtractionPanel results={results} components={components} selectedIndex={selectedIndex} />
          </div>

          {/* Row 4 — Manufacturing Plan + Complexity (full width). Surfaces the
             planner's machine ranking, op sequence, feeds/speeds + a derived
             complexity summary that the cost/extraction cards don't show. */}
          {components.some((c) => (c.planner ?? c.agentic) || (c.manufacturing_processes ?? []).length) && (
            <ManufacturingPlanCard components={components} selectedIndex={selectedIndex} />
          )}
        </>
      )}
    </>
  );
}
