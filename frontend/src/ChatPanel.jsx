// The "04 / FOLLOW YOUR CURIOSITY" card: ask a question, see the answer and the
// passages it came from.
//
// This component owns the conversation. App.jsx gives it a document and an API address,
// and gives it a new `key` whenever the document changes, which makes React replace
// this component and so clears the history automatically.
//
// The part worth studying is isValidAnswer() below. The backend already validates every
// citation, and this re-checks the same rules in the browser. That is on purpose: it is
// the difference between "the server promised this is correct" and "this response in
// front of me really is correct". If anything is wrong, we show an error rather than
// display an answer with a page reference we could not verify.

import { useEffect, useRef, useState } from "react";

const MAX_QUESTION_CHARACTERS = 1000;

// How many question-and-answer pairs we keep on screen. Older ones drop off the top.
const MAX_CHAT_TURNS = 12;

// Limits that mirror the backend's own, so an impossible response is rejected.
const MAX_ANSWER_CHARACTERS = 8000;
const MAX_SOURCES = 4;
const MAX_EXCERPT_CHARACTERS = 1400;
const MAX_CONTEXT_QUESTION_CHARACTERS = 1000;

// Matches a proper citation marker like "[Page 4]". Starting at [1-9] means "[Page 0]"
// is not accepted. The "g" flag is needed to find every marker, not just the first.
const PAGE_CITATION_PATTERN = /\[Page ([1-9]\d*)\]/g;
const SINGLE_PAGE_CITATION = /\[Page [1-9]\d*\]/;

// Matches a page number written as prose, such as "see page 4" or "pp. 7", capturing
// the number so it can be compared against the answer's real citations. The "g" flag
// is needed to find every prose mention, not just the first.
const PROSE_PAGE_NUMBER = /\b(?:pages?|pp?\.)\s*(\d+)/gi;

// Splits an answer into paragraphs on blank lines.
const PARAGRAPH_BREAK = /\n\s*\n/;

// Check the answer's basic fields are the right types and within sane limits.
function hasValidAnswerShape(result, document) {
  return (
    result?.document_id === document.document_id &&
    typeof result.answer === "string" &&
    result.answer.trim() !== "" &&
    result.answer.length <= MAX_ANSWER_CHARACTERS &&
    typeof result.insufficient_evidence === "boolean" &&
    Array.isArray(result.sources) &&
    result.sources.length <= MAX_SOURCES &&
    // context_question is optional, so null and undefined are both fine. If it IS
    // present it must be a string of reasonable length.
    (result.context_question == null ||
      (typeof result.context_question === "string" &&
        result.context_question.length <= MAX_CONTEXT_QUESTION_CHARACTERS))
  );
}

// Check every source passage, and collect the set of pages they refer to.
//
// Returns the Set of page numbers, or null if any source is unusable. Returning null
// rather than false lets the caller tell "invalid" apart from "valid but empty".
//
// The page_number > document.page_count check is the important one: it means a page
// beyond the end of the real PDF can never be displayed as a source.
function collectSourcePages(result, document) {
  const seenChunkIds = new Set();
  const sourcePages = new Set();

  for (const source of result.sources) {
    const isUsable =
      source &&
      typeof source.chunk_id === "string" &&
      source.chunk_id !== "" &&
      !seenChunkIds.has(source.chunk_id) &&
      Number.isInteger(source.page_number) &&
      source.page_number >= 1 &&
      source.page_number <= document.page_count &&
      typeof source.excerpt === "string" &&
      source.excerpt.trim() !== "" &&
      source.excerpt.length <= MAX_EXCERPT_CHARACTERS;

    if (!isUsable) {
      return null;
    }

    seenChunkIds.add(source.chunk_id);
    sourcePages.add(source.page_number);
  }

  return sourcePages;
}

// Find every page number cited as "[Page N]".
function findPageCitations(answerText) {
  const matches = answerText.matchAll(PAGE_CITATION_PATTERN);
  return Array.from(matches, (match) => Number(match[1]));
}

// Allow a page number in normal prose only if the answer also cites that page.
//
// This mirrors check_prose_page_numbers_are_cited in backend/chat.py, and it has to:
// if this were stricter than the backend, the browser would reject answers the server
// had already approved, and the user would see an error for a correct answer.
//
// A natural answer to "what does page 6 describe?" starts "Page 6 describes...". That is
// fine, because the matching "[Page 6]" marker is checked against the real passages.
// Saying "page 99" while citing only page 6 is not fine and is still rejected.
//
// A bracketed reference spelled any other way, such as "[page 6]", is always rejected:
// it imitates the citation format without matching it.
function prosePageNumbersAreCited(answerText, citations) {
  const withoutMarkers = answerText.replace(PAGE_CITATION_PATTERN, "");

  if (withoutMarkers.toLowerCase().includes("[page")) {
    return false;
  }

  const prosePages = Array.from(
    withoutMarkers.matchAll(PROSE_PAGE_NUMBER),
    (match) => Number(match[1]),
  );

  for (const page of prosePages) {
    if (!citations.includes(page)) {
      return false;
    }
  }
  return true;
}

// Require every paragraph to carry its own citation, so one marker at the end cannot
// appear to support earlier claims that nothing actually backs up.
function everyParagraphIsCited(answerText) {
  const paragraphs = answerText.split(PARAGRAPH_BREAK);

  for (const paragraph of paragraphs) {
    if (paragraph.trim() === "") {
      continue;
    }
    if (!SINGLE_PAGE_CITATION.test(paragraph)) {
      return false;
    }
  }
  return true;
}

// Require the cited pages and the listed sources to describe exactly the same pages,
// checked in both directions.
function citationsMatchSources(citations, sourcePages) {
  if (citations.length === 0 || sourcePages.size === 0) {
    return false;
  }

  const everyCitationHasASource = citations.every((page) => sourcePages.has(page));
  const everySourceIsCited = Array.from(sourcePages).every((page) =>
    citations.includes(page),
  );

  return everyCitationHasASource && everySourceIsCited;
}

// The full check, as a sequence of steps. Returns true only if the answer and all of
// its citations are verifiable against this document.
function isValidAnswer(result, document) {
  if (!hasValidAnswerShape(result, document)) {
    return false;
  }

  const sourcePages = collectSourcePages(result, document);
  if (sourcePages === null) {
    return false;
  }

  // Collect the cited pages first, because the prose check below needs them.
  const citations = findPageCitations(result.answer);

  if (!prosePageNumbersAreCited(result.answer, citations)) {
    return false;
  }

  // An honest "not enough evidence" must claim no sources and no citations at all.
  if (result.insufficient_evidence) {
    return result.sources.length === 0 && citations.length === 0;
  }

  if (!everyParagraphIsCited(result.answer)) {
    return false;
  }

  return citationsMatchSources(citations, sourcePages);
}

// One question-and-answer pair. A turn is in exactly one of three states: still
// loading, finished with a result, or failed with an error.
function ChatTurn({ turn, isLastTurn, isSending, onRetry }) {
  return (
    <li>
      <div className="chat-message chat-user">
        <p className="message-label">You</p>
        <p className="message-text">{turn.question}</p>
      </div>
      <div className="chat-message chat-assistant">
        <p className="message-label">PaperLense</p>

        {turn.result ? (
          <>
            {turn.result.insufficient_evidence && (
              <span className="evidence-note">Not enough evidence</span>
            )}
            {turn.result.context_question && (
              <p className="chat-context">
                Following up on: {turn.result.context_question}
              </p>
            )}
            <p className="message-text">{turn.result.answer}</p>
            {turn.result.sources.length > 0 && (
              <details className="chat-sources">
                <summary>Supporting passages ({turn.result.sources.length})</summary>
                {turn.result.sources.map((source) => (
                  <figure className="source-passage" key={source.chunk_id}>
                    <figcaption>
                      Source excerpt · <strong>Page {source.page_number}</strong>
                    </figcaption>
                    <blockquote>{source.excerpt}</blockquote>
                  </figure>
                ))}
              </details>
            )}
          </>
        ) : turn.error ? (
          <div className="chat-error" role="alert">
            <strong>We couldn’t prepare an answer</strong>
            <p>{turn.error}</p>
            {/* Retry is offered only on the most recent turn, so the conversation
                cannot be rewritten from the middle. */}
            {isLastTurn && (
              <button
                type="button"
                className="button button-secondary"
                disabled={isSending}
                onClick={onRetry}
              >
                Retry answer
              </button>
            )}
          </div>
        ) : (
          <p className="chat-loading" role="status">
            <span className="spinner" /> Finding supporting passages and preparing an
            answer…
          </p>
        )}
      </div>
    </li>
  );
}

export default function ChatPanel({ document, isUploading, apiBaseUrl }) {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [inputError, setInputError] = useState("");
  const [status, setStatus] = useState("");

  // The in-flight request, so we can cancel it and recognise stale replies.
  const request = useRef(null);

  // A counter for turn IDs. A ref rather than state because it must increment
  // immediately, and it is never displayed.
  const nextTurnId = useRef(0);

  // Cancel any running request when this component is removed. App.jsx gives each
  // document a different key, so replacing the PDF unmounts this panel and this
  // clean-up stops the old document's answer arriving afterwards.
  useEffect(() => {
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, []);

  async function sendQuestion(event, retryTurn = null) {
    // Stop the browser from reloading the page when the form is submitted.
    event?.preventDefault();

    // Nothing to do without a document, and only one question at a time.
    if (!document || isUploading || request.current) {
      return;
    }

    // A retry re-sends that turn's original question; otherwise use the input box.
    const submittedQuestion = (retryTurn ? retryTurn.question : question).trim();

    if (!submittedQuestion || submittedQuestion.length > MAX_QUESTION_CHARACTERS) {
      setInputError("Enter a question between 1 and 1,000 characters.");
      return;
    }

    const controller = new AbortController();
    request.current = controller;
    setIsSending(true);
    setInputError("");
    setStatus("");

    let turnId;
    if (retryTurn) {
      // Reuse the existing turn and clear its error, so the retry replaces the failed
      // answer in place instead of adding a duplicate question to the history.
      turnId = retryTurn.id;
      setTurns((previous) =>
        previous.map((turn) =>
          turn.id === turnId ? { ...turn, error: null } : turn,
        ),
      );
    } else {
      nextTurnId.current += 1;
      turnId = nextTurnId.current;
      // Add the turn with no result yet, which is what renders the loading spinner.
      // slice(-MAX_CHAT_TURNS) keeps only the newest 12 turns.
      setTurns((previous) =>
        [
          ...previous,
          { id: turnId, question: submittedQuestion, result: null, error: null },
        ].slice(-MAX_CHAT_TURNS),
      );
      setQuestion("");
    }

    const timeoutId = setTimeout(() => controller.abort(), 110_000);

    try {
      const response = await fetch(
        `${apiBaseUrl}/api/documents/${encodeURIComponent(document.document_id)}/chat`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: submittedQuestion }),
          signal: controller.signal,
        },
      );

      const result = await response.json();

      // Stale check: a newer request has replaced this one, so drop this reply.
      if (request.current !== controller) {
        return;
      }

      if (!response.ok) {
        throw new Error(
          typeof result?.detail === "string"
            ? result.detail
            : "The question could not be answered. Check its length and try again.",
        );
      }

      // Verify every citation before displaying anything.
      if (!isValidAnswer(result, document)) {
        throw new Error(
          "The server returned an invalid answer or page references. Please try again.",
        );
      }

      setTurns((previous) =>
        previous.map((turn) =>
          turn.id === turnId ? { ...turn, result, error: null } : turn,
        ),
      );

      // Announced to screen readers through the hidden live region at the bottom.
      setStatus(
        result.insufficient_evidence
          ? "No supporting evidence was found for this question."
          : `Answer ready with ${result.sources.length} supporting passages.`,
      );
    } catch (failure) {
      if (request.current !== controller) {
        return;
      }

      let message = failure.message;
      if (failure.name === "AbortError") {
        message = "The answer took too long. Please try again.";
      } else if (failure instanceof TypeError) {
        message = "Could not reach PaperLense. Check the backend connection and try again.";
      } else if (failure instanceof SyntaxError) {
        message = "The server returned an unreadable answer. Please try again.";
      }

      // Attach the error to its own turn, so each question keeps its own outcome.
      setTurns((previous) =>
        previous.map((turn) =>
          turn.id === turnId ? { ...turn, error: message } : turn,
        ),
      );
    } finally {
      clearTimeout(timeoutId);
      if (request.current === controller) {
        request.current = null;
        setIsSending(false);
      }
    }
  }

  function handleKeyDown(event) {
    // Enter sends, Shift+Enter makes a new line. The isComposing check matters for
    // languages typed with an input method editor, where Enter confirms the characters
    // being composed and must not submit the form.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      sendQuestion(event);
    }
  }

  const isInputDisabled = !document || isUploading;

  return (
    <section className="card chat-card" id="paper-chat" aria-labelledby="chat-title">
      <div className="summary-header">
        <div>
          <p className="card-eyebrow">04 / FOLLOW YOUR CURIOSITY</p>
          <h2 id="chat-title">Ask your paper</h2>
          <p className="card-description">
            A conversation with the evidence, one question at a time.
          </p>
        </div>
        <span className="chat-badge">Answers with page references</span>
      </div>

      <p className="chat-privacy">
        PaperLense finds relevant passages locally. To generate an answer, it sends your
        question and those passages to configured providers as needed, in order from
        Gemini to Groq to OpenRouter.
      </p>

      {turns.length === 0 ? (
        <div className="chat-empty">
          <span aria-hidden="true">?</span>
          <div>
            <h3>A question is a good place to start.</h3>
            <p>
              {document
                ? "Ask about the research question, methods, or results. We’ll look for supporting passages first."
                : "Upload a paper above to start a document-grounded conversation."}
            </p>
          </div>
        </div>
      ) : (
        <ol className="chat-history" aria-label="Conversation about the current paper">
          {turns.map((turn, index) => (
            <ChatTurn
              key={turn.id}
              turn={turn}
              isLastTurn={index === turns.length - 1}
              isSending={isSending}
              onRetry={() => sendQuestion(null, turn)}
            />
          ))}
        </ol>
      )}

      <form className="chat-form" onSubmit={sendQuestion} aria-busy={isSending}>
        <label htmlFor="paper-question">Your question</label>
        <textarea
          id="paper-question"
          // value + onChange makes this a "controlled input": React state is the single
          // source of truth for what the box contains.
          value={question}
          rows={3}
          maxLength={MAX_QUESTION_CHARACTERS}
          disabled={isInputDisabled}
          readOnly={isSending}
          placeholder="What would you like to understand about this paper?"
          aria-describedby="chat-input-help"
          onChange={(event) => {
            setQuestion(event.target.value);
            setInputError("");
          }}
          onKeyDown={handleKeyDown}
        />
        <div className="chat-form-footer">
          <p id="chat-input-help">
            Enter to send · Shift + Enter for a new line{" "}
            <span>{question.length}/1,000</span>
          </p>
          <button
            type="submit"
            className="button button-primary"
            disabled={isInputDisabled || isSending || !question.trim()}
          >
            {isSending ? "Preparing answer…" : "Send question"}
          </button>
        </div>
        {inputError && (
          <p className="chat-input-error" role="alert">
            {inputError}
          </p>
        )}
      </form>

      <p className="chat-footnote">
        Answers use retrieved text, not the full paper. Check the cited passages against
        the original. This workspace keeps the latest 12 questions; replacing the PDF
        clears the conversation.
      </p>

      {/* Visually hidden, but screen readers announce changes to it. */}
      <p className="visually-hidden" role="status" aria-live="polite">
        {status}
      </p>
    </section>
  );
}
