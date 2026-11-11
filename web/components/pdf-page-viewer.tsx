"use client";

import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { LoaderCircle } from "lucide-react";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

export function PdfPageViewer({
  fileName,
  pageNumber,
}: {
  fileName: string;
  pageNumber: number;
}) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [width, setWidth] = useState<number>(320);
  const containerRef = useRef<HTMLDivElement>(null);
  const fileUrl = `/api/documents/file?name=${encodeURIComponent(fileName)}`;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setWidth(Math.max(200, el.clientWidth - 8));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="flex w-full flex-col items-center">
      <Document
        file={fileUrl}
        loading={
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Loading PDF…
          </div>
        }
        error={
          <div className="w-full rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-600 dark:text-red-400">
            Could not load PDF. Ensure the backend is running and the file exists in the configured PDF folder.
          </div>
        }
        onLoadSuccess={({ numPages: n }) => setNumPages(n)}
        className="max-w-full"
      >
        <Page
          pageNumber={pageNumber}
          width={width}
          renderTextLayer
          renderAnnotationLayer
          className="overflow-hidden rounded-md border shadow-sm"
          loading={
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <LoaderCircle className="size-4 animate-spin" /> Rendering page…
            </div>
          }
        />
      </Document>
      {numPages && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Page {Math.min(pageNumber, numPages)} of {numPages}
        </p>
      )}
    </div>
  );
}
