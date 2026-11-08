// The "03 / CONNECT THE IDEAS" card: the five-section AI summary, its loading state,
// its error state, and the retry button.
//
// The summary normally starts by itself after a successful upload. The button here is
// the manual retry for when that automatic attempt failed.
//
// This component has no state. App.jsx owns the summary data and passes it in, and the
// button calls onGenerateSummary().

import Icon from "./Icon.jsx";

// The five sections, in the exact order they are displayed. Each entry is
// [key in the backend's JSON, heading shown to the user].
//
// This list is the single source of truth for the five sections. App.jsx imports it to
// check that a response really contains all five before showing anything, so the list
// and the validation can never disagree.
export const SUMMARY_SECTIONS = [
  ["title_authors_abstract", "Title & Authors and Abstract"],
  ["problem_statement", "Problem Statement"],
  ["methodology", "Methodology"],
  ["key_results", "Key Results"],
  ["conclusion", "Conclusion"],
];

export default function SummaryCard({
  document,
  summary,
  summaryError,
  isSummarizing,
  isUploading,
  onGenerateSummary,
}) {
  // The button says "Retry summary" after a failure and "Generate Summary" otherwise.
  const generateButtonLabel = summaryError ? "Retry summary" : "Generate Summary";

  return (
    <section
      className="card summary-card"
      id="paper-summary"
      aria-labelledby="summary-title"
      aria-busy={isSummarizing}
    >
      <div className="summary-header">
        <div>
          <p className="card-eyebrow">03 / CONNECT THE IDEAS</p>
          <h2 id="summary-title">Your paper, understood</h2>
          <p className="card-description">
            Five focused sections. One clearer picture of the research.
          </p>
        </div>
        {summary ? (
          <span className="summary-ready">
            <Icon name="check" size={17} /> Summary ready
          </span>
        ) : (
          <button
            type="button"
            className="button button-primary"
            onClick={onGenerateSummary}
            // Disabled unless there is a document and nothing else is in progress.
            // This is what stops a second request being sent while one is running.
            disabled={!document || isUploading || isSummarizing}
          >
            {isSummarizing ? (
              <>
                <span className="spinner" /> Generating summary…
              </>
            ) : (
              <>
                <Icon name="book" size={18} />
                {generateButtonLabel}
              </>
            )}
          </button>
        )}
      </div>

      {!summary && (
        <p className="summary-privacy">
          Summaries try Gemini first, then Groq and OpenRouter in that order when
          configured and needed. If generation fails, you can retry here.
        </p>
      )}

      {summaryError && (
        <div className="error-message summary-error" role="alert">
          <Icon name="alert" size={20} />
          <div>
            <strong>We couldn’t generate the summary</strong>
            <p>{summaryError}</p>
          </div>
        </div>
      )}

      <div className="summary-status" aria-live="polite" aria-atomic="true">
        {isSummarizing && (
          <p className="summary-loading" role="status">
            Reading your paper and connecting its ideas. This can take up to 90 seconds.
          </p>
        )}
        {summary && (
          <p className="summary-source" role="status">
            Summary generated for {document.filename}. Based on the extracted text from{" "}
            {summary.source_page_count}{" "}
            {summary.source_page_count === 1 ? "page" : "pages"}.
          </p>
        )}
      </div>

      {summary ? (
        <>
          <div className="summary-sections">
            {SUMMARY_SECTIONS.map(([key, heading], index) => (
              <section
                className="summary-section"
                key={key}
                aria-labelledby={`summary-${key}`}
              >
                <div className="summary-section-heading">
                  {/* padStart turns 1 into "01", so the numbers line up. */}
                  <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  <h3 id={`summary-${key}`}>{heading}</h3>
                </div>
                <p>{summary.summary[key]}</p>
              </section>
            ))}
          </div>
          <p className="summary-footnote">
            AI-generated from extracted text using {summary.model}. Check important
            details against the original paper; figures and images are not analyzed.
          </p>
        </>
      ) : (
        // Shown only when there is nothing to display and nothing going wrong, so the
        // card is never completely blank.
        !isSummarizing &&
        !summaryError && (
          <div className="summary-empty">
            <Icon name="book" size={23} />
            <p>
              {document
                ? "Your paper is ready. Its summary will explore the question, methods, findings, and conclusions."
                : "Upload a paper above. Its structured summary will start automatically."}
            </p>
          </div>
        )
      )}
    </section>
  );
}
