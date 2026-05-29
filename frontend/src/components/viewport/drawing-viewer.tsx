"use client";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  FileImage, Loader2, AlertCircle, ZoomIn, ZoomOut,
  ChevronLeft, ChevronRight, ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";

interface DrawingViewerProps {
  fileUrl: string | null;
  mimeType?: string | null;
  title?: string;
}

/** Decide whether the source is a PDF (vs. a raster image). */
function looksLikePdf(url: string | null, mime?: string | null): boolean {
  if (mime && mime.toLowerCase().includes("pdf")) return true;
  if (!url) return false;
  // Strip any query/signature suffix before testing the extension.
  const path = url.split("?")[0].toLowerCase();
  return path.endsWith(".pdf");
}

export function DrawingViewer({ fileUrl, mimeType, title }: DrawingViewerProps) {
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
    ? <PdfViewer fileUrl={fileUrl} title={title} />
    : <ImageViewer fileUrl={fileUrl} title={title} />;
}

// ───────────────────────────────────────────────────────────────────────────
// PDF
// ───────────────────────────────────────────────────────────────────────────

function PdfViewer({ fileUrl, title }: { fileUrl: string; title?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<any>(null);
  const renderTaskRef = useRef<any>(null);
  const lastAvailRef = useRef(0);

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

  // Render the active page whenever page/zoom/doc changes.
  const renderPage = useCallback(async () => {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas) return;
    try {
      renderTaskRef.current?.cancel?.();
      const pdfPage = await doc.getPage(page);

      // Fit the page to the scroll container's content width (p-4 = 16px each
      // side), then apply the user's zoom on top. Engineering-drawing PDFs are
      // large-format, so rendering at native size overflows the panel — fitting
      // to width shows the whole sheet by default.
      const base = pdfPage.getViewport({ scale: 1 });
      const scroller = scrollRef.current;
      const avail = scroller ? Math.max(160, scroller.clientWidth - 32) : base.width;
      lastAvailRef.current = avail;
      const cssScale = (avail / base.width) * zoom;

      const dpr = window.devicePixelRatio || 1;
      const viewport = pdfPage.getViewport({ scale: cssScale * dpr });
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / dpr}px`;
      canvas.style.height = `${viewport.height / dpr}px`;
      const task = pdfPage.render({ canvasContext: ctx, viewport });
      renderTaskRef.current = task;
      await task.promise;
    } catch (err: unknown) {
      const name = err instanceof Error ? err.name : (err as { name?: string } | null)?.name;
      if (name !== "RenderingCancelledException") {
        setError(err instanceof Error ? err.message : "Failed to render page");
      }
    }
  }, [page, zoom]);

  useEffect(() => { if (!loading && !error) renderPage(); }, [loading, error, renderPage]);

  // Re-fit when the panel resizes (window resize, sidebar collapse, tab switch).
  // Guarded against scrollbar-induced jitter so it can't loop with renderPage.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || loading || error) return;
    const ro = new ResizeObserver(() => {
      const avail = Math.max(160, scroller.clientWidth - 32);
      if (Math.abs(avail - lastAvailRef.current) < 4) return;
      renderPage();
    });
    ro.observe(scroller);
    return () => ro.disconnect();
  }, [loading, error, renderPage]);

  return (
    <div className="relative flex h-full w-full flex-col bg-muted/20">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-background/80 px-3 py-2 backdrop-blur-sm">
        <span className="truncate text-xs text-muted-foreground">{title ?? "Drawing"}</span>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" className="h-7 w-7" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} title="Previous page">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="min-w-16 text-center text-xs tabular-nums text-muted-foreground">
            {numPages ? `${page} / ${numPages}` : "—"}
          </span>
          <Button variant="outline" size="icon" className="h-7 w-7" disabled={page >= numPages} onClick={() => setPage((p) => Math.min(numPages, p + 1))} title="Next page">
            <ChevronRight className="h-4 w-4" />
          </Button>
          <div className="mx-1 h-5 w-px bg-border" />
          <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.max(0.25, +(z - 0.25).toFixed(2)))} title="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <span className="min-w-12 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
          <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.min(6, +(z + 0.25).toFixed(2)))} title="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button asChild variant="outline" size="icon" className="h-7 w-7" title="Open raw PDF">
            <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
          </Button>
        </div>
      </div>

      <div ref={scrollRef} className="relative flex-1 overflow-auto">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">Loading drawing…</span>
            </div>
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center px-4 text-center">
            <div className="flex flex-col items-center gap-2">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <span className="text-sm text-destructive">{error}</span>
              <Button asChild variant="outline" size="sm" className="mt-1">
                <a href={fileUrl} target="_blank" rel="noreferrer">Open raw file</a>
              </Button>
            </div>
          </div>
        )}
        <div className="flex min-h-full items-start justify-center p-4">
          <canvas ref={canvasRef} className="rounded-sm shadow-md ring-1 ring-border" />
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Raster image
// ───────────────────────────────────────────────────────────────────────────

function ImageViewer({ fileUrl, title }: { fileUrl: string; title?: string }) {
  const [scale, setScale] = useState(1);
  const [error, setError] = useState(false);

  return (
    <div className="relative flex h-full w-full flex-col bg-muted/20">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-background/80 px-3 py-2 backdrop-blur-sm">
        <span className="truncate text-xs text-muted-foreground">{title ?? "Drawing"}</span>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setScale((s) => Math.max(0.25, s - 0.25))} title="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </Button>
          <span className="min-w-12 text-center text-xs tabular-nums text-muted-foreground">{Math.round(scale * 100)}%</span>
          <Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setScale((s) => Math.min(5, s + 0.25))} title="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </Button>
          <Button asChild variant="outline" size="icon" className="h-7 w-7" title="Open raw image">
            <a href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /></a>
          </Button>
        </div>
      </div>
      <div className="relative flex-1 overflow-auto">
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center px-4 text-center">
            <div className="flex flex-col items-center gap-2">
              <AlertCircle className="h-8 w-8 text-destructive" />
              <span className="text-sm text-destructive">Failed to load drawing</span>
            </div>
          </div>
        ) : (
          <div className="flex min-h-full items-start justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={title ?? "Drawing"}
              onError={() => setError(true)}
              style={{ width: `${scale * 100}%`, maxWidth: "none" }}
              className="rounded-sm shadow-md ring-1 ring-border"
            />
          </div>
        )}
      </div>
    </div>
  );
}
