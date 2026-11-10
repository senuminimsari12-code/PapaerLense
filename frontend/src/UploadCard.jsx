// The "01 / YOUR DOCUMENT" card: the drop zone, the Choose PDF button, the selected
// file details, and any upload error.
//
// This component holds no state of its own. It displays what App.jsx tells it to and
// reports user actions back through two callbacks:
//
//   onFilesSelected(files) - the user picked or dropped files; App.jsx uploads them.
//   onDraggingChange(bool) - the user is dragging a file over the drop zone.
//
// Keeping it this way means all the upload logic stays in one place in App.jsx, and
// this file is only about what the user sees.

import Icon from "./Icon.jsx";
import { formatFileSize } from "./fileSize.js";
import { useTranslation } from "./interfacePreferences.jsx";

export default function UploadCard({
  selectedFile,
  document,
  isUploading,
  isDragging,
  error,
  fileInputRef,
  onFilesSelected,
  onDraggingChange,
}) {
  const t = useTranslation();
  function handleDrop(event) {
    // Without preventDefault the browser would navigate away and open the PDF itself.
    event.preventDefault();
    onDraggingChange(false);
    onFilesSelected(event.dataTransfer.files);
  }

  function handleDragOver(event) {
    // preventDefault here is what tells the browser this element accepts a drop.
    event.preventDefault();
    if (!isUploading) {
      onDraggingChange(true);
    }
  }

  function handleDragLeave(event) {
    // dragleave also fires when the pointer moves onto a child element, which would
    // make the highlight flicker. This check ignores those inner moves and only turns
    // the highlight off when the pointer has really left the drop zone.
    if (!event.currentTarget.contains(event.relatedTarget)) {
      onDraggingChange(false);
    }
  }

  function handleFileInputChange(event) {
    onFilesSelected(event.target.files);
    // Clearing the input's value lets the user pick the SAME file again. Without this,
    // re-selecting an identical filename would fire no change event and nothing would
    // happen, which looks like the button is broken.
    event.target.value = "";
  }

  // The drop zone, heading and button text all change depending on what is happening.
  // These are worked out here so the JSX below stays readable.
  let dropZoneHeading;
  let dropZoneMessage;
  if (isUploading) {
    dropZoneHeading = "Bringing your paper into focus…";
    dropZoneMessage = "Reading pages and extracting text.";
  } else if (document) {
    dropZoneHeading = "Your paper is ready";
    dropZoneMessage = "Text extracted. Ready to explore.";
  } else if (isDragging) {
    dropZoneHeading = "Drop your paper here";
    dropZoneMessage = "or choose a file from your device";
  } else {
    dropZoneHeading = "Drop your research paper here";
    dropZoneMessage = "or choose a file from your device";
  }

  let selectedFileStatus;
  if (isUploading) {
    selectedFileStatus = "Extracting text";
  } else if (document) {
    selectedFileStatus = "Processed successfully";
  } else {
    selectedFileStatus = "Selected file";
  }

  return (
    <section className="card upload-card" aria-labelledby="upload-title" aria-busy={isUploading}>
      <div className="card-eyebrow">
        <span>{t("01 / YOUR DOCUMENT")}</span>
        <span className="file-type">PDF</span>
      </div>
      <h2 id="upload-title">{t("Start with your paper")}</h2>
      <p className="card-description">{t("One paper. A fresh perspective.")}</p>

      {/*
        The real file input is hidden, because browsers style it inconsistently and it
        cannot be made to match this design. The visible button below calls .click() on
        it instead. tabIndex={-1} keeps it out of the keyboard tab order so keyboard
        users reach the styled button rather than this hidden element.
      */}
      <input
        ref={fileInputRef}
        id="pdf-input"
        className="visually-hidden"
        type="file"
        tabIndex={-1}
        accept=".pdf,application/pdf"
        aria-label={t("Choose a research paper PDF")}
        disabled={isUploading}
        onChange={handleFileInputChange}
      />

      <div
        className={`drop-zone ${isDragging ? "dragging" : ""} ${document ? "has-document" : ""}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span className={`upload-symbol ${isUploading ? "processing" : ""}`}>
          <Icon name={document ? "check" : "upload"} size={30} />
        </span>
        <h3>{t(dropZoneHeading)}</h3>
        <p>{t(dropZoneMessage)}</p>
        <button
          className={`button ${document ? "button-secondary" : "button-primary"}`}
          type="button"
          disabled={isUploading}
          onClick={() => fileInputRef.current.click()}
        >
          {isUploading ? (
            <>
              <span className="spinner" />{" "}{t("Processing PDF")}</>
          ) : (
            <>
              {t(selectedFile ? "Choose another PDF" : "Choose PDF")}
              <Icon name="arrow" size={17} />
            </>
          )}
        </button>
        <span className="upload-limit">{t("PDF only")}{" "}<span aria-hidden="true">·</span>{" "}{t("Up to 20 MB (20 MiB)")}</span>
      </div>

      {selectedFile && (
        <div className="selected-file">
          <span className="file-icon">
            <Icon name="file" size={22} />
          </span>
          <div>
            <p title={selectedFile.name}>{selectedFile.name}</p>
            <span>
              {selectedFile.size < 1024
                ? t("{count} bytes", { count: selectedFile.size })
                : formatFileSize(selectedFile.size)}{" "}
              <span aria-hidden="true">·</span> {t(selectedFileStatus)}
            </span>
          </div>
          {document && <Icon name="check" size={19} className="success-icon" />}
        </div>
      )}

      {/*
        aria-live="polite" makes a screen reader announce whatever appears in here,
        without interrupting what it is currently saying. This is how a blind user hears
        that the upload finished.
      */}
      <div className="status-region" aria-live="polite" aria-atomic="true">
        {isUploading && (
          <p className="processing-message" role="status">{t("Processing your PDF. This can take a moment.")}</p>
        )}
        {document && (
          <p className="success-message" role="status">
            <Icon name="check" size={17} /> {t(document.page_count === 1
              ? "Successfully extracted {count} page."
              : "Successfully extracted {count} pages.", { count: document.page_count })}
          </p>
        )}
      </div>

      {/* role="alert" is announced immediately, because an error needs attention now. */}
      {error && (
        <div className="error-message" role="alert">
          <Icon name="alert" size={20} />
          <div>
            <strong>{t("We couldn’t process this file")}</strong>
            <p>{t(error)}</p>
          </div>
        </div>
      )}

      <p className="privacy-note">
        <Icon name="shield" size={16} />
        <span>{t("The backend processes your PDF and keeps extracted text temporarily for this browser session. The automatic summary sends extracted text to configured AI providers. Upload only public or non-sensitive papers.")}</span>
      </p>
    </section>
  );
}
