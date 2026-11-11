"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { Crosshair, LoaderCircle, Minus, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

const MIN_ZOOM = 0.6;
const MAX_ZOOM = 2.5;

export function PdfPageViewer({
  fileName,
  pageNumber,
  projectId,
}: {
  fileName: string;
  pageNumber: number;
  projectId?: string;
}) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [width, setWidth] = useState<number>(560);
  const [zoom, setZoom] = useState<number>(1);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const fileUrl = `/api/documents/file?name=${encodeURIComponent(fileName)}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setWidth(Math.max(240, el.clientWidth - 16));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const scrollToPage = useCallback((p: number) => {
    const el = pageRefs.current[p - 1];
    const container = containerRef.current;
    if (el && container) {
      container.scrollTo({ top: el.offsetTop - container.offsetTop, behavior: "smooth" });
    }
  }, []);

  // Scroll to the cited page whenever the selection changes (or the doc loads).
  useEffect(() => {
    if (!numPages) return;
    const t = window.setTimeout(() => scrollToPage(Math.min(Math.max(1, pageNumber), numPages)), 60);
    return () => window.clearTimeout(t);
  }, [pageNumber, numPages, scrollToPage]);

  // Ctrl/Cmd + wheel to zoom.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z + (e.deltaY < 0 ? 0.1 : -0.1))));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

  return (
    <div className="flex h-full w-full flex-col">
      {/* Toolbar */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b bg-background/60 px-2">
        <span className="text-[11px] text-muted-foreground">
          {numPages ? `${numPages} pages` : "Loading…"} · cited page {pageNumber}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => scrollToPage(pageNumber)}
            className="mr-1 flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title={`Go to cited page ${pageNumber}`}
          >
            <Crosshair className="size-3" /> Cited p.{pageNumber}
          </button>
          <button
            onClick={() => setZoom((z) => clampZoom(z - 0.15))}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Zoom out"
            disabled={zoom <= MIN_ZOOM}
          >
            <Minus className="size-3.5" />
          </button>
          <button
            onClick={() => setZoom(1)}
            className="w-10 text-center text-[11px] font-medium tabular-nums text-muted-foreground transition-colors hover:text-foreground"
            title="Reset zoom"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            onClick={() => setZoom((z) => clampZoom(z + 0.15))}
            className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Zoom in"
            disabled={zoom >= MAX_ZOOM}
          >
            <Plus className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Scrollable document */}
      <div ref={containerRef} className="min-h-0 flex-1 overflow-auto p-3">
        <Document
          file={fileUrl}
          loading={
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Loading PDF…
            </div>
          }
          error={
            <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-600 dark:text-red-400">
              Could not load PDF. Ensure the backend is running and the file exists.
            </div>
          }
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          className="flex flex-col items-center gap-3"
        >
          {Array.from({ length: numPages ?? 0 }, (_, i) => i + 1).map((p) => (
            <div
              key={p}
              ref={(el) => { pageRefs.current[p - 1] = el; }}
              className={cn(
                "rounded-md transition-shadow",
                p === pageNumber && "ring-2 ring-amber-400/60"
              )}
            >
              <Page
                pageNumber={p}
                width={width * zoom}
                renderTextLayer
                renderAnnotationLayer
                className="overflow-hidden rounded-md border shadow-sm"
                loading={
                  <div className="flex items-center gap-2 py-10 text-xs text-muted-foreground">
                    <LoaderCircle className="size-3.5 animate-spin" />
                  </div>
                }
              />
              <p className="py-1 text-center text-[10px] tabular-nums text-muted-foreground">
                {p}{p === pageNumber ? " · cited" : ""}
              </p>
            </div>
          ))}
        </Document>
      </div>
    </div>
  );
}
