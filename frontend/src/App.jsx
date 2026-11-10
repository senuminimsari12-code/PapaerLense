// The top-level component. This is the file to read to understand what the frontend
// actually DOES, because it owns all the state and both network requests.
//
// The display is split into separate components so this file stays about behaviour:
//   UploadCard.jsx      - the drop zone and upload errors.
//   DocumentPreview.jsx - the extracted text preview.
//   SummaryCard.jsx     - the five-section summary.
//   ChatPanel.jsx       - the questions and answers.
//   PageSections.jsx    - the header, footer and other fixed text.
//
// There are two things that happen here, and following them is the whole picture:
//
//   uploadFiles()     runs when the user picks or drops a PDF. It checks the file,
//                     POSTs it to /api/upload, stores the result, then immediately
//                     starts the summary.
//   generateSummary() POSTs to /api/documents/{id}/summary and stores the five
//                     sections. It runs automatically after an upload, and again if
//                     the user clicks Retry.
//
// Why there are useRef values as well as useState:
// useState is for data we want to DISPLAY. Changing it re-renders the component.
// useRef is for data we need to CHECK during an async function. A ref holds one value
// that is shared across renders and can be read immediately, whereas state updates are
// not visible until the next render. That difference is what makes refs the right tool
// for "is a request already running?" and "is this response still wanted?".

import { useRef, useState } from "react";
import { InterfacePreferences } from "./interfacePreferences.jsx";
import { apiErrorMessage } from "./translations.js";

import ChatPanel from "./ChatPanel.jsx";
import DocumentPreview from "./DocumentPreview.jsx";
import SummaryCard, { SUMMARY_SECTIONS } from "./SummaryCard.jsx";
import UploadCard from "./UploadCard.jsx";
import {
  FeatureListSection,
  HowItWorksSection,
  IntroSection,
  SiteFooter,
  SiteHeader,
  SkipLink,
} from "./PageSections.jsx";

// Re-exported here because that is where the tests and older imports look for it.
// The function itself lives in fileSize.js, next to the card that uses it.
export { formatFileSize } from "./fileSize.js";

// The only place the backend address is configured. An optional VITE_API_BASE_URL in
// the root .env overrides the default. The .replace removes a trailing slash so we
// never build a URL with a double slash in it.
//
// Only VITE_-prefixed variables are visible to frontend code. That is deliberate and
// important: it is what keeps the API keys in .env out of the browser bundle.
const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

// 20 MiB, matching the backend's limit. Checking here too means an oversized file is
// rejected instantly without a pointless upload.
const MAX_FILE_BYTES = 20 * 1024 * 1024;

// How long we wait before giving up on each request, in milliseconds. The summary
// deadline is slightly under the backend's 90-second budget plus overhead, so the
// backend normally gets to finish and report a real error first.
const UPLOAD_TIMEOUT_MS = 120_000;
const SUMMARY_TIMEOUT_MS = 110_000;

// Turn a caught fetch error into a sentence for the user.
//
// The three cases are the three ways a fetch can fail, and they need different advice:
//   AbortError   - our own timer gave up, or the request was cancelled.
//   TypeError    - fetch itself failed, so the backend is unreachable.
//   SyntaxError  - a reply arrived but was not valid JSON, so it was not from our API.
// Anything else is an Error we threw ourselves, and its message is already suitable.
function describeRequestFailure(failure, messages) {
  if (failure.name === "AbortError") {
    return messages.timedOut;
  }
  if (failure instanceof TypeError) {
    return messages.unreachable;
  }
  if (failure instanceof SyntaxError) {
    return messages.unreadable;
  }
  return failure.message;
}

// Check the upload response really contains everything we need before trusting it.
//
// Why bother, when the backend is ours? Because a proxy, a tunnel or a misconfigured
// port can return a 200 with completely different JSON. Checking here means the UI
// never shows "success" for a response it cannot actually display.
function isCompleteUploadResult(result) {
  return (
    typeof result?.document_id === "string" &&
    result.document_id.trim() !== "" &&
    Number.isInteger(result.page_count) &&
    result.page_count >= 1 &&
    Number.isInteger(result.character_count) &&
    result.character_count >= 1 &&
    typeof result.preview === "string" &&
    result.preview.trim() !== "" &&
    typeof result.filename === "string"
  );
}

// Check a summary response has all five sections, filled in, for the right document.
function isCompleteSummaryResult(result, expectedDocumentId) {
  const hasAllFiveSections = SUMMARY_SECTIONS.every(
    ([key]) =>
      typeof result?.summary?.[key] === "string" &&
      result.summary[key].trim().length > 0,
  );

  return (
    result?.document_id === expectedDocumentId &&
    hasAllFiveSections &&
    typeof result.model === "string" &&
    result.model.trim() !== "" &&
    Number.isInteger(result.source_page_count) &&
    result.source_page_count >= 1 &&
    Number.isInteger(result.source_character_count) &&
    result.source_character_count >= 1
  );
}

export default function App() {
  return (
    <InterfacePreferences>
      {(preferences) => <Workspace preferences={preferences} />}
    </InterfacePreferences>
  );
}

function Workspace({ preferences }) {
  // What the user sees.
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadedDocument, setUploadedDocument] = useState(null);
  const [citationPage, setCitationPage] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState("");
  const [isSummarizing, setIsSummarizing] = useState(false);

  // The hidden <input type="file">, so the styled button can open the file picker.
  const fileInputRef = useRef(null);

  // True while an upload is in flight. Blocks a second upload immediately, without
  // waiting for a re-render the way the isUploading state would.
  const uploadInProgress = useRef(false);

  // The AbortController of the summary request we currently want. Any response whose
  // controller is not this one is stale and gets thrown away.
  const summaryRequest = useRef(null);

  // The document the user most recently accepted. Used to confirm an automatic summary
  // still belongs to the document on screen.
  const currentDocument = useRef(null);

  async function uploadFiles(files) {
    // Ignore a second upload while one is already running, and ignore an empty drop.
    if (uploadInProgress.current || !files.length) {
      return;
    }

    // Clear the previous result BEFORE validating the new file. If the new file turns
    // out to be invalid, the user must not be left looking at the old document's
    // preview and summary while an error message claims the upload failed.
    currentDocument.current = null;
    setUploadedDocument(null);
    setCitationPage(null);

    // Cancel any summary still running for the old document, so its response cannot
    // arrive later and appear to belong to the new one.
    summaryRequest.current?.abort();
    summaryRequest.current = null;

    setSummary(null);
    setSummaryError("");
    setIsSummarizing(false);
    setError("");
    setSelectedFile(files[0]);
    setIsDragging(false);

    // Checks we can do without contacting the backend at all.
    if (files.length !== 1) {
      setError("Choose one PDF at a time.");
      return;
    }

    const file = files[0];
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Choose a PDF file. Other document formats are not supported.");
      return;
    }
    if (file.size === 0) {
      setError("This file is empty. Choose a PDF containing readable text.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("This file exceeds the 20 MB (20 MiB) upload limit.");
      return;
    }

    // FormData sends the file as multipart/form-data, which is what the backend's
    // /api/upload endpoint expects. The field name "file" must match the backend.
    const formData = new FormData();
    formData.append("file", file);

    uploadInProgress.current = true;
    setIsUploading(true);

    // An AbortController lets us cancel the request. The timer below calls .abort(),
    // which makes the fetch reject with an AbortError.
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

    try {
      const response = await fetch(`${API_BASE_URL}/api/upload`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      const result = await response.json();

      if (!response.ok) {
        // FastAPI puts its error text in "detail". Throwing here sends it to the catch
        // block below, which displays it.
        throw apiErrorMessage(result?.detail, response.status, "upload");
      }

      if (!isCompleteUploadResult(result)) {
        throw new Error("The server returned an incomplete result. Please try again.");
      }

      // Register the accepted document before starting its summary.
      //
      // Setting the ref first is what makes the automatic summary safe: generateSummary
      // checks currentDocument.current, so it will only run for the document we just
      // accepted. React's Strict Mode re-runs some code twice in development, but it
      // does not replay event handlers, so this cannot fire two summaries.
      currentDocument.current = result;
      setUploadedDocument(result);

      // Deliberately not awaited. The preview and Q&A stay usable while the summary is
      // still being generated, instead of the whole page waiting on it.
      generateSummary(result);
    } catch (uploadError) {
      setError(
        uploadError?.operation ? uploadError : describeRequestFailure(uploadError, {
          timedOut: "Processing took too long. Please try again with a smaller PDF.",
          unreachable:
            "Could not reach PaperLense. Check that the backend is running at the configured API address, then try again.",
          unreadable:
            "The server returned an unreadable response. Check the backend and try again.",
        }),
      );
    } finally {
      // Runs whether we succeeded or failed, so the UI never stays stuck on "uploading".
      clearTimeout(timeoutId);
      uploadInProgress.current = false;
      setIsUploading(false);
    }
  }

  async function generateSummary(targetDocument) {
    // Four reasons to do nothing. Together these are what stop duplicate and stale
    // summary requests.
    const noDocument = !targetDocument;
    const documentIsNoLongerCurrent = currentDocument.current !== targetDocument;
    const alreadyGenerating = Boolean(summaryRequest.current);
    const alreadyHaveThisSummary =
      summary?.document_id === targetDocument?.document_id;

    if (
      noDocument ||
      documentIsNoLongerCurrent ||
      alreadyGenerating ||
      alreadyHaveThisSummary
    ) {
      return;
    }

    const documentId = targetDocument.document_id;
    const controller = new AbortController();
    summaryRequest.current = controller;

    setIsSummarizing(true);
    setSummaryError("");

    const timeoutId = setTimeout(() => controller.abort(), SUMMARY_TIMEOUT_MS);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/documents/${encodeURIComponent(documentId)}/summary`,
        { method: "POST", signal: controller.signal },
      );

      const result = await response.json();

      // The stale check. While we were waiting, the user may have uploaded a different
      // PDF, which replaced summaryRequest.current. If so this reply is for the old
      // document and must be dropped silently, not displayed.
      if (summaryRequest.current !== controller) {
        return;
      }

      if (!response.ok) {
        throw apiErrorMessage(result?.detail, response.status, "summary");
      }

      if (!isCompleteSummaryResult(result, documentId)) {
        throw new Error("The server returned an incomplete summary. Please try again.");
      }

      setSummary(result);
    } catch (summaryFailure) {
      // The same stale check again: a cancelled request must not show an error for a
      // document the user has already moved on from.
      if (summaryRequest.current !== controller) {
        return;
      }

      setSummaryError(
        summaryFailure?.operation ? summaryFailure : describeRequestFailure(summaryFailure, {
          timedOut: "Summary generation took too long. Please try again.",
          unreachable:
            "Could not reach PaperLense. Check the backend connection and try again.",
          unreadable:
            "The server returned an unreadable summary response. Please try again.",
        }),
      );
    } finally {
      clearTimeout(timeoutId);
      // Only clear the "in progress" state if this is still the current request.
      // A newer request may have replaced it, and that one is still running.
      if (summaryRequest.current === controller) {
        summaryRequest.current = null;
        setIsSummarizing(false);
      }
    }
  }

  function openCitationPage(documentId, page) {
    const active = currentDocument.current;
    if (!active || active.document_id !== documentId ||
        !Number.isSafeInteger(page) || page < 1 || page > active.page_count) {
      return;
    }
    // A new selection also refocuses the preview when the same citation is clicked.
    setCitationPage({ page });
  }

  return (
    <div className="app-shell">
      <SkipLink />
      <SiteHeader preferences={preferences} />

      <main id="main" tabIndex={-1}>
        <IntroSection />

        <div className="workspace-grid">
          <UploadCard
            selectedFile={selectedFile}
            document={uploadedDocument}
            isUploading={isUploading}
            isDragging={isDragging}
            error={error}
            fileInputRef={fileInputRef}
            onFilesSelected={uploadFiles}
            onDraggingChange={setIsDragging}
          />
          <DocumentPreview
            document={uploadedDocument}
            isUploading={isUploading}
            file={selectedFile}
            citationPage={citationPage}
          />
        </div>

        <SummaryCard
          document={uploadedDocument}
          summary={summary}
          summaryError={summaryError}
          isSummarizing={isSummarizing}
          isUploading={isUploading}
          onGenerateSummary={() => generateSummary(uploadedDocument)}
        />

        {/*
          The `key` is the important part here. When the key changes React throws the
          old ChatPanel away and builds a fresh one, which clears the entire question
          history. That is how uploading a new PDF discards the old conversation, with
          no clean-up code of our own.
        */}
        <ChatPanel
          key={uploadedDocument?.document_id || "no-document"}
          document={uploadedDocument}
          isUploading={isUploading}
          apiBaseUrl={API_BASE_URL}
          onOpenCitation={openCitationPage}
        />

        <FeatureListSection />
        <HowItWorksSection />
      </main>

      <SiteFooter />
    </div>
  );
}
