"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  FileImage, Loader2, AlertCircle, ZoomIn, ZoomOut,
  ChevronLeft, ChevronRight, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface DrawingViewerProps {
  fileUrl: string | null;
  mimeType?: string | null;
  title?: string;
  /** When provided, the viewer renders its toolbar into this header slot
   *  (via portal) so it lines up with the 3D/2D switch. Falls back to a
   *  floating top-right cluster when absent. */
  controlsSlot?: HTMLElement | null;
}

/** Decide whether the source is a PDF (vs. a raster image). */
function looksLikePdf(url: string | null, mime?: string | null): boolean {
  if (mime && mime.toLowerCase().includes("pdf")) return true;
  if (!url) return false;
  // Strip any query/signature suffix before testing the extension.
  const path = url.split("?")[0].toLowerCase();
  return path.endsWith(".pdf");
}

export function DrawingViewer({ fileUrl, mimeType, title, controlsSlot }: DrawingViewerProps) {
  const isPdf = looksLikePdf(fileUrl, mimeType);

  if (!fileUrl) {
    return (
      <div className="viewport-grid flex h-full w-full flex-col items-center justify-center">
        <FileImage className="mb-2 h-12 w-12 text-muted-foreground/50" />
        <span className="text-sm text-muted-foreground">No drawing available</span>
      </div>
    );
  }

  return isPdf
    ? <PdfViewer fileUrl={fileUrl} title={title} controlsSlot={controlsSlot} />
    : <ImageViewer fileUrl={fileUrl} title={title} controlsSlot={controlsSlot} />;
}

/** Wrap a toolbar so it either portals into the shared header slot (inline,
 *  aligned with the 3D/2D switch) or floats top-right inside the viewer. */
function Toolbar({ slot, children }: { slot?: HTMLElement | null; children: React.ReactNode }) {
  const bar = (
    <div
      className={cn(
        "z-10 flex items-center justify-end gap-1 rounded-lg border border-border bg-background/90 p-1 shadow-sm backdrop-blur-sm",
        slot ? "flex-nowrap" : "absolute right-2 top-2 max-w-[calc(100%-1rem)] flex-wrap",
      )}
    >
      {children}
    </div>
  );
  return slot ? createPortal(bar, slot) : bar;
}

// ───────────────────────────────────────────────────────────────────────────
// PDF
// ───────────────────────────────────────────────────────────────────────────

function PdfViewer({ fileUrl, title, controlsSlot }: { fileUrl: string; title?: string; controlsSlot?: HTMLElement | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<any>(null);
  const renderTaskRef = useRef<any>(null);
  const lastAvailRef = useRef({ w: 0, h: 0 });
  // Serialization guards: pdf.js throws "Cannot use the same canvas during
  // multiple render() operations" if two renders overlap. The load-effect and
  // the ResizeObserver both call renderPage, so we (a) run at most one render
  // at a time and (b) coalesce any request that arrives mid-render into a
  // single re-run afterwards.
  const renderingRef = useRef(false);
  const rerenderRef = useRef(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  // Zoom multiplier applied on top of fit-to-width (1 = fit the panel width).
  const [zoom, setZoom] = useState(1);

  // Load the document once per URL.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPage(1);
    setZoom(1);

    (async () => {
      try {
        const pdfjsLib: any = await import("pdfjs-dist/build/pdf");
        pdfjsLib.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        const task = pdfjsLib.getDocument({ url: fileUrl });
        const doc = await task.promise;
        if (cancelled) { doc.destroy?.(); return; }
        docRef.current = doc;
        setNumPages(doc.numPages);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load PDF");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel?.();
      docRef.current?.destroy?.();
      docRef.current = null;
    };
  }, [fileUrl]);

  // Render the active page whenever page/zoom/doc changes. Serialized so two
  // renders never share the canvas concurrently.
  const renderPage = useCallback(async () => {
    if (renderingRef.current) { rerenderRef.current = true; return; }
    renderingRef.current = true;
    try {
      do {
        rerenderRef.current = false;
        const doc = docRef.current;
        const canvas = canvasRef.current;
        if (!doc || !canvas) break;

        // Cancel AND await any in-flight task so the canvas is free before the
        // next render() — awaiting is what prevents the "same canvas" error.
        if (renderTaskRef.current) {
          try { renderTaskRef.current.cancel(); } catch { /* ignore */ }
          try { await renderTaskRef.current.promise; } catch { /* cancellation */ }
          renderTaskRef.current = null;
        }

        try {
          const pdfPage = await doc.getPage(page);

          // Fit the WHOLE page inside the scroll container (contain), then apply
          // the user's zoom. zoom=1 shows the full sheet with no scrollbar.
          const base = pdfPage.getViewport({ scale: 1 });
          const scroller = scrollRef.current;
          const availW = scroller ? Math.max(120, scroller.clientWidth - 24) : base.width;
          const availH = scroller ? Math.max(120, scroller.clientHeight - 24) : base.height;
          lastAvailRef.current = { w: availW, h: availH };
          const fit = Math.min(availW / base.width, availH / base.height);
          const cssScale = fit * zoom;

          const dpr = window.devicePixelRatio || 1;
          const viewport = pdfPage.getViewport({ scale: cssScale * dpr });
          const ctx = canvas.getContext("2d");
          if (!ctx) break;
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${viewport.width / dpr}px`;
          canvas.style.height = `${viewport.height / dpr}px`;
          const task = pdfPage.render({ canvasContext: ctx, viewport });
          renderTaskRef.current = task;
          await task.promise;
          if (renderTaskRef.current === task) renderTaskRef.current = null;
        } catch (err: unknown) {
          const name = err instanceof Error ? err.name : (err as { name?: string } | null)?.name;
          if (name !== "RenderingCancelledException") {
            setError(err instanceof Error ? err.message : "Failed to render page");
          }
        }
      } while (rerenderRef.current); // a request arrived mid-render — run once more
    } finally {
      renderingRef.current = false;
    }
  }, [page, zoom]);

  useEffect(() => { if (!loading && !error) renderPage(); }, [loading, error, renderPage]);

  // Re-fit when the panel resizes (window resize, sidebar collapse, tab switch).
  // Guarded against scrollbar-induced jitter so it can't loop with renderPage.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || loading || error) return;
    const ro = new ResizeObserver(() => {
      const w = Math.max(120, scroller.clientWidth - 24);
      const h = Math.max(120, scroller.clientHeight - 24);
      // Re-fit on EITHER dimension changing (contain depends on both).
      if (Math.abs(w - lastAvailRef.current.w) < 4 && Math.abs(h - lastAvailRef.current.h) < 4) return;
      renderPage();
    });
    ro.observe(scroller);
    return () => ro.disconnect();
  }, [loading, error, renderPage]);

  return (
    <div className="relative flex h-full w-full flex-col bg-muted/20">
      {/* Toolbar: portals into the shared header slot (aligned with the 3D/2D
         switch) when available, else floats top-right inside the viewer. */}
      <Toolbar slot={controlsSlot}>
        <Button variant="outline" size="icon" className="h-7 w-7" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} title="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="min-w-14 text-center text-xs tabular-nums text-muted-foreground">
          {numPages ? `${page} / ${numPages}` : "—"}
        </span>
        <Button variant="outline" size="icon" className="h-7 w-7" disabled={page >= numPages} onClick={() => setPage((p) => Math.min(numPages, p + 1))} title="Next page">
          <ChevronRight className="h-4 w-4" />
        </Button>
        <div className="mx-0.5 h-5 w-px bg-border" />
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.max(0.25, +(z - 0.25).toFixed(2)))} title="Zoom out">
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="min-w-11 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.min(6, +(z + 0.25).toFixed(2)))} title="Zoom in">
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button asChild variant="outline" size="icon" className="h-7 w-7" title="Open raw PDF">
          <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
        </Button>
      </Toolbar>

      <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-auto">
        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">Loading drawing…</span>
            </div>
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center px-4 text-center">
            <div className="flex flex-col items-center gap-2">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <span className="text-sm text-destructive">{error}</span>
              <Button asChild variant="outline" size="sm" className="mt-1">
                <a href={fileUrl} target="_blank" rel="noreferrer">Open raw file</a>
              </Button>
            </div>
          </div>
        )}
        {/* At zoom ≤ 1 the page fits (contain) → center it. When zoomed in it
           overflows → top-align so the user can scroll to every edge. */}
        <div className={cn("flex min-h-full min-w-full justify-center p-3", zoom > 1 ? "items-start" : "items-center")}>
          <canvas ref={canvasRef} className="rounded-sm shadow-md ring-1 ring-border" />
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Raster image
// ───────────────────────────────────────────────────────────────────────────

function ImageViewer({ fileUrl, title, controlsSlot }: { fileUrl: string; title?: string; controlsSlot?: HTMLElement | null }) {
  const [scale, setScale] = useState(1);
  const [error, setError] = useState(false);

  return (
    <div className="relative flex h-full w-full flex-col bg-muted/20">
      <Toolbar slot={controlsSlot}>
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setScale((s) => Math.max(0.25, s - 0.25))} title="Zoom out">
          <ZoomOut className="h-4 w-4" />
        </Button>
        <span className="min-w-11 text-center text-xs tabular-nums text-muted-foreground">{Math.round(scale * 100)}%</span>
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setScale((s) => Math.min(5, s + 0.25))} title="Zoom in">
          <ZoomIn className="h-4 w-4" />
        </Button>
        <Button asChild variant="outline" size="icon" className="h-7 w-7" title="Open raw image">
          <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
        </Button>
      </Toolbar>
      <div className="relative min-h-0 flex-1 overflow-auto">
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center px-4 text-center">
            <div className="flex flex-col items-center gap-2">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <span className="text-sm text-destructive">Failed to load drawing</span>
            </div>
          </div>
        ) : (
          <div className={cn("flex min-h-full min-w-full justify-center p-3", scale > 1 ? "items-start" : "items-center")}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={title ?? "Drawing"}
              onError={() => setError(true)}
              // scale=1 → fit inside the panel (contain, no scrollbar);
              // scale>1 → grow past the panel and scroll.
              style={scale > 1
                ? { width: `${scale * 100}%`, maxWidth: "none" }
                : { maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
              className="rounded-sm shadow-md ring-1 ring-border"
            />
          </div>
        )}
      </div>
    </div>
  );
}
