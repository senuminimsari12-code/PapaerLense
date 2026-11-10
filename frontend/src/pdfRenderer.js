import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

export function openPdf(bytes) {
  return getDocument({ data: new Uint8Array(bytes), isEvalSupported: false });
}
