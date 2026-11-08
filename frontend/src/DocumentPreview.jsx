// The "02 / TAKE A CLOSER LOOK" card: page count, character count, and the first few
// thousand characters of the extracted text.
//
// This card proves the extraction actually worked. Everything it shows comes from the
// backend's upload response, so a user can see the real text rather than taking the
// summary on trust.
//
// It renders one of two things: the document, or an empty placeholder.

import Icon from "./Icon.jsx";

function EmptyPreview({ isUploading }) {
  // The decorative paper illustration shown before anything is uploaded.
  return (
    <div className="preview-empty">
      <div className="paper-illustration" aria-hidden="true">
        <div className="paper-back" />
        <div className="paper-front">
          <span className="paper-mini-label">PAPERLENSE</span>
          <div className="paper-rule wide" />
          <div className="paper-rule wide" />
          <div className="paper-rule medium" />
          <div className="paper-separator" />
          <div className="paper-rule" />
          <div className="paper-rule" />
          <div className="paper-rule short" />
          <span className="paper-lens">
            <Icon name="text" size={23} />
          </span>
        </div>
      </div>
      <h3>
        {isUploading ? "A little clarity is on its way" : "Your paper, at a glance"}
      </h3>
      <p>
        {isUploading
          ? "Your real document preview will appear once extraction finishes."
          : "Upload a PDF to see its page count and a preview of the extracted text."}
      </p>
      <span className="empty-label">
        <span />
        {isUploading
          ? "Extracting your document"
          : "A clear starting point for your research"}
      </span>
    </div>
  );
}

export default function DocumentPreview({ document, isUploading }) {
  return (
    <section className="card preview-card" aria-labelledby="preview-title">
      <div className="preview-heading">
        <div>
          <p className="card-eyebrow">02 / TAKE A CLOSER LOOK</p>
          <h2 id="preview-title">Document preview</h2>
        </div>
        <span className={`preview-badge ${document ? "ready" : ""}`}>
          {document ? "Text extracted" : "Awaiting your paper"}
        </span>
      </div>

      {document ? (
        <div className="document-content">
          <dl className="document-stats">
            <div>
              <dt>Pages</dt>
              {/* toLocaleString adds thousands separators, e.g. 44609 -> "44,609". */}
              <dd>{document.page_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Characters</dt>
              <dd>{document.character_count.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Format</dt>
              <dd>PDF</dd>
            </div>
          </dl>
          <div className="text-preview-heading">
            <span>
              <Icon name="text" size={16} /> EXTRACTED TEXT
            </span>
            <span>First 4,000 characters max.</span>
          </div>
          {/*
            <pre> keeps the line breaks exactly as the PDF had them, which matters for
            judging whether extraction worked. tabIndex={0} lets a keyboard user focus
            this box so they can scroll it with the arrow keys.
          */}
          <pre className="text-preview" tabIndex={0} aria-label="Extracted text preview">
            {document.preview}
          </pre>
          <p className="preview-footnote">
            Original page numbers are preserved. Reading order may vary in complex
            layouts.
          </p>
        </div>
      ) : (
        <EmptyPreview isUploading={isUploading} />
      )}
    </section>
  );
}
