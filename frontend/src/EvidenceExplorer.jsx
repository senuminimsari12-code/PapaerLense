// The Evidence Explorer: the passages PaperLens really sent to the AI for one answer.
//
// Everything shown here comes from the `evidence` list in the chat response, which the
// backend fills from the same retrieved chunks it sent to the provider. This component
// never fetches anything, never asks an AI for a quotation and never rewrites a
// passage, so the text on screen is the paper's own extracted text.
//
// Two rules keep it honest:
//   1. No evidence means no panel. We never show an empty or invented one.
//   2. The current document and page count constrain every navigation button.

import { fillLabel, labelsForLanguage, passageCountLabel } from "./evidenceLabels.js";

// Mirrors MAX_RETRIEVED_CHUNKS in backend/retrieval.py: the most passages ever sent.
export const MAX_EVIDENCE = 4;

// The longest passage we will display, matching the backend's chunk size.
const MAX_EXCERPT_CHARACTERS = 1400;

// Keep only the evidence items we can actually display and trust.
//
// Input:  the raw evidence list from the response, and the current document.
// Output: a new list holding just the usable items, in the order they arrived.
//
// An unusable item is dropped rather than shown, so a missing page number or a missing
// source ID can never become a card with a blank label or a broken page button. The
// page_number check against document.page_count is the important one: a page beyond the
// end of the real PDF is never displayed and never offered for navigation.
export function usableEvidence(evidence, document) {
  if (!Array.isArray(evidence) || !document) {
    return [];
  }

  const usable = [];
  const seenChunkIds = new Set();

  for (const item of evidence) {
    const isUsable =
      item &&
      typeof item.chunk_id === "string" &&
      item.chunk_id !== "" &&
      !seenChunkIds.has(item.chunk_id) &&
      Number.isInteger(item.page_number) &&
      item.page_number >= 1 &&
      item.page_number <= document.page_count &&
      typeof item.excerpt === "string" &&
      item.excerpt.trim() !== "" &&
      item.excerpt.length <= MAX_EXCERPT_CHARACTERS &&
      typeof item.cited === "boolean";

    if (isUsable) {
      seenChunkIds.add(item.chunk_id);
      usable.push(item);
    }
  }

  return usable.slice(0, MAX_EVIDENCE);
}

// One evidence card: which source it is, which page it came from, its text, and the
// action that opens that page in the document preview.
function EvidenceCard({ item, sourceNumber, labels, canOpenPage, onOpenSourcePage }) {
  const pageLabel = fillLabel(labels.page, { page: item.page_number });

  return (
    <li className="evidence-card">
      <div className="evidence-card-header">
        <span className="evidence-card-source">
          {fillLabel(labels.source, { number: sourceNumber })} · <strong>{pageLabel}</strong>
        </span>
        <span className={item.cited ? "evidence-tag is-cited" : "evidence-tag"}>
          {item.cited ? labels.cited : labels.notCited}
        </span>
      </div>

      <blockquote className="evidence-card-text">{item.excerpt}</blockquote>

      {canOpenPage ? (
        <button
          type="button"
          className="evidence-open-button"
          aria-label={fillLabel(labels.openSourcePage, { page: item.page_number })}
          onClick={() => onOpenSourcePage(item.page_number)}
        >
          {labels.openSource}
        </button>
      ) : (
        // Said plainly rather than offering a button that would not work.
        <p className="evidence-open-unavailable">
          {fillLabel(labels.pageNotInPreview, { page: item.page_number })}
        </p>
      )}
    </li>
  );
}

export default function EvidenceExplorer({
  evidence,
  document,
  insufficientEvidence = false,
  language = "en",
  onOpenSourcePage = null,
}) {
  const labels = labelsForLanguage(language);
  const passages = usableEvidence(evidence, document);

  // Nothing genuine to show, so show nothing at all. This covers an answer with no
  // retrieved passages and a response whose evidence items were all unusable.
  if (passages.length === 0) {
    return null;
  }

  return (
    <details className="evidence-explorer">
      <summary>
        <span className="evidence-explorer-title">{labels.title}</span>
        <span className="evidence-explorer-count">
          {" · "}
          {passageCountLabel(labels, passages.length, insufficientEvidence)}
        </span>
      </summary>

      <p className="evidence-explorer-note">{labels.note}</p>

      <ol className="evidence-card-list">
        {passages.map((item, index) => (
          <EvidenceCard
            key={item.chunk_id}
            item={item}
            sourceNumber={index + 1}
            labels={labels}
            canOpenPage={
              onOpenSourcePage !== null
            }
            onOpenSourcePage={onOpenSourcePage}
          />
        ))}
      </ol>
    </details>
  );
}
