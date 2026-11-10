import { useEffect, useRef, useState } from "react";
import { useTranslation } from "./interfacePreferences.jsx";

export default function CitedPdfPage({ file, page }) {
  const [pdf, setPdf] = useState(null);
  const [failed, setFailed] = useState(false);
  const t = useTranslation();

  useEffect(() => {
    let stopped = false;
    let loadingTask;

    async function load() {
      try {
        const { openPdf } = await import("./pdfRenderer.js");
        const bytes = await file.arrayBuffer();
        if (stopped) return;
        loadingTask = openPdf(bytes);
        const document = await loadingTask.promise;
        if (!stopped) setPdf(document);
      } catch {
        if (!stopped) setFailed(true);
      }
    }

    load();
    return () => {
      stopped = true;
      loadingTask?.destroy().catch(() => {});
    };
  }, [file]);

  if (failed) return <p role="alert">{t("The original PDF could not be opened in this browser.")}</p>;
  if (!pdf) return <p role="status">{t("Loading PDF page…")}</p>;
  return <PdfPageCanvas key={page} pdf={pdf} page={page} />;
}

function PdfPageCanvas({ pdf, page }) {
  const canvas = useRef(null);
  const [status, setStatus] = useState("loading");
  const t = useTranslation();

  useEffect(() => {
    let stopped = false;
    let renderTask;

    async function renderPage() {
      try {
        const pdfPage = await pdf.getPage(page);
        if (stopped) return;
        const viewport = pdfPage.getViewport({ scale: 1 });
        // Keep unusually large pages from creating unbounded canvas allocations.
        const scale = 1600 / Math.max(viewport.width, viewport.height);
        const display = pdfPage.getViewport({ scale });
        const element = canvas.current;
        element.width = Math.max(1, Math.ceil(display.width));
        element.height = Math.max(1, Math.ceil(display.height));
        renderTask = pdfPage.render({ canvas: element, viewport: display });
        await renderTask.promise;
        if (!stopped) setStatus("ready");
      } catch {
        if (!stopped) setStatus("failed");
      }
    }

    renderPage();
    return () => {
      stopped = true;
      renderTask?.cancel();
    };
  }, [pdf, page]);

  return (
    <>
      {status === "loading" && <p role="status">{t("Loading PDF page…")}</p>}
      {status === "failed" && <p role="alert">{t("This PDF page could not be displayed.")}</p>}
      <canvas ref={canvas} hidden={status !== "ready"} role="img"
        aria-label={t("Original PDF page {page}", { page })} />
    </>
  );
}
