import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App.jsx";
import { openPdf } from "./pdfRenderer.js";

vi.mock("./pdfRenderer.js", () => ({ openPdf: vi.fn() }));

// Citation buttons split the text into nodes; compare the whole answer paragraph.
const answerParagraph = (text) => (_content, node) =>
  node.matches("p.message-text") && node.textContent === text;

const uploaded = {
  document_id: "paper-one", filename: "first.pdf", page_count: 3,
  character_count: 120, preview: "Page 2\nClassifier research preview",
};
const question = "What accuracy does the classifier achieve?";
const answer = {
  document_id: uploaded.document_id,
  answer: "The classifier achieved 93 percent accuracy. [Page 2]",
  sources: [{ chunk_id: "chunk-1", page_number: 2, excerpt: "The classifier achieved 93 percent accuracy on the test dataset." }],
  insufficient_evidence: false, model: "test-model", context_question: null,
};
const ok = (data) => ({ ok: true, json: async () => data });
const failure = (detail) => ({ ok: false, json: async () => ({ detail }) });

function choose(name = "first.pdf") {
  const file = new File(["pdf bytes"], name, { type: "application/pdf" });
  file.arrayBuffer = async () => new ArrayBuffer(8);
  fireEvent.change(screen.getByLabelText("Choose a research paper PDF"), {
    target: { files: [file] },
  });
}

async function openPaper() {
  render(<App />);
  choose();
  await screen.findByText("Page 2 Classifier research preview");
  await screen.findByText("Summary ready");
}

function send(text = question) {
  fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((url) => Promise.resolve(url.endsWith("/summary")
    ? ok({ document_id: url.split("/").at(-2), model: "test-model", source_page_count: 3,
        source_character_count: 120, summary: {
          title_authors_abstract: "Summary fixture title and abstract.",
          problem_statement: "Summary fixture problem.", methodology: "Summary fixture method.",
          key_results: "Summary fixture results.", conclusion: "Summary fixture conclusion.",
        } })
    : ok(uploaded))));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("Grounded paper Q&A", () => {
  it("guards chat until upload succeeds and sends nothing on typing", async () => {
    render(<App />);
    expect(screen.getByRole("textbox", { name: "Your question" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Send question" }).disabled).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
    choose();
    await screen.findByText("Page 2 Classifier research preview");
    const input = screen.getByRole("textbox", { name: "Your question" });
    fireEvent.change(input, { target: { value: "What" } });
    expect(input.disabled).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(2); // Upload and automatic summary; typing sends nothing.
  });

  it("sends only an explicit question and displays cited answer and source excerpts", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok(answer));
    send("  " + question + "  ");
    await screen.findByText(answerParagraph(answer.answer));
    expect(screen.getByText(question)).toBeTruthy();
    const [url, options] = fetch.mock.calls[2];
    expect(url).toBe("http://localhost:8000/api/documents/paper-one/chat");
    expect(JSON.parse(options.body)).toEqual({ question });
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    const sources = screen.getByText("Supporting passages (1)");
    expect(sources.closest("details").open).toBe(false);
    fireEvent.click(sources);
    expect(sources.closest("details").open).toBe(true);
    expect(screen.getByText("Page 2", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText(answer.sources[0].excerpt, { selector: "blockquote" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Your question" }).value).toBe("");
    expect(screen.getByText("Page 2 Classifier research preview")).toBeTruthy();
    expect(screen.getByText("Summary ready")).toBeTruthy();
  });

  it("supports Enter to send and Shift+Enter for a new line", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok(answer));
    const input = screen.getByRole("textbox", { name: "Your question" });
    fireEvent.change(input, { target: { value: question } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(fetch).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(fetch).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText(answerParagraph(answer.answer));
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("rejects blank or oversized questions even when a form is submitted directly", async () => {
    await openPaper();
    const input = screen.getByRole("textbox", { name: "Your question" });
    fireEvent.submit(input.closest("form"));
    expect(screen.getByRole("alert").textContent).toContain("1,000 characters");
    fireEvent.change(input, { target: { value: "x".repeat(1001) } });
    fireEvent.submit(input.closest("form"));
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("shows progress and prevents duplicate submissions", async () => {
    await openPaper();
    const pending = deferred();
    fetch.mockReturnValueOnce(pending.promise);
    const input = screen.getByRole("textbox", { name: "Your question" });
    input.focus();
    fireEvent.change(input, { target: { value: "What is the main result?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText(/Finding supporting passages and preparing/)).toBeTruthy();
    expect(input.disabled).toBe(false);
    expect(input.readOnly).toBe(true);
    expect(document.activeElement).toBe(input);
    expect(screen.getByRole("button", { name: "Preparing answer…" }).disabled).toBe(true);
    fireEvent.submit(input.closest("form"));
    fireEvent.submit(input.closest("form"));
    expect(fetch).toHaveBeenCalledTimes(3);
    await act(async () => pending.resolve(ok(answer)));
    expect(screen.getByText(answerParagraph(answer.answer))).toBeTruthy();
    expect(input.readOnly).toBe(false);
    expect(document.activeElement).toBe(input);
  });

  it("shows provider failure honestly and retries the same turn", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(failure("The AI provider is temporarily unavailable."));
    send();
    await screen.findByText("The AI provider is temporarily unavailable.");
    expect(screen.queryByText(answerParagraph(answer.answer))).toBeNull();
    fetch.mockResolvedValueOnce(ok(answer));
    fireEvent.click(screen.getByRole("button", { name: "Retry answer" }));
    await screen.findByText(answerParagraph(answer.answer));
    expect(fetch.mock.calls[3][1].body).toBe(fetch.mock.calls[2][1].body);
    expect(screen.getAllByText(question)).toHaveLength(1);
  });

  it("shows a genuine insufficient-evidence response without source claims", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok({ ...answer, answer: "The retrieved passages do not establish this answer.", sources: [], insufficient_evidence: true, model: null }));
    send("How do I bake sourdough bread?");
    await screen.findByText("Not enough evidence");
    expect(screen.getByText("The retrieved passages do not establish this answer.")).toBeTruthy();
    expect(screen.queryByText(/Supporting passages \(/)).toBeNull();
  });

  it("makes follow-up context visible and keeps answers as plain text", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok({ ...answer, context_question: "Earlier classifier question", answer: "<script>ignore me</script> Results are reported. [Page 2]" }));
    send("What about its dataset?");
    await screen.findByText("Following up on: Earlier classifier question");
    expect(screen.getByText(/<script>ignore me<\/script>/)).toBeTruthy();
    expect(document.querySelector(".chat-history script")).toBeNull();
  });

  it.each([
    { ...answer, document_id: "different-paper" },
    { ...answer, answer: "An invented citation. [Page 999]" },
    { ...answer, sources: [{ ...answer.sources[0], page_number: 4 }] },
    { ...answer, sources: [] },
    { ...answer, sources: [answer.sources[0], answer.sources[0]] },
    { ...answer, answer: "Uncited claim." },
    { ...answer, answer: "Uncited paragraph.\n\nA cited paragraph. [Page 2]" },
    { ...answer, answer: "Claim. [Page 2] [Pages 999]" },
    { ...answer, context_question: { invalid: true } },
    { ...answer, insufficient_evidence: true },
    null,
  ])("rejects malformed or mismatched answers %#", async (result) => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok(result));
    send();
    await screen.findByText(/server returned an invalid answer/);
    expect(screen.getByRole("button", { name: "Retry answer" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^\[Page / })).toBeNull();
  });

  it("displays a multi-paragraph answer when each paragraph cites a source", async () => {
    await openPaper();
    const text = "The classifier was tested. [Page 2]\n\nAccuracy is 93 percent. [Page 2]";
    fetch.mockResolvedValueOnce(ok({ ...answer, answer: text }));
    send();
    await screen.findByText(/The classifier was tested/);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Supporting passages (1)")).toBeTruthy();
  });

  it.each([
    [() => Promise.reject(new TypeError("Failed to fetch")), "Could not reach PaperLense"],
    [() => Promise.resolve({ ok: true, json: async () => { throw new SyntaxError("HTML instead"); } }), "unreadable answer"],
    [() => Promise.resolve({ ok: false, json: async () => ({ detail: [{ msg: "invalid" }] }) }), "Check its length"],
  ])("handles transport and unreadable errors %#", async (response, message) => {
    await openPaper();
    fetch.mockImplementationOnce(response);
    send();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(message);
    expect(screen.getByRole("textbox", { name: "Your question" }).disabled).toBe(false);
  });

  it("bounds a stalled browser request and offers retry", async () => {
    await openPaper();
    vi.useFakeTimers();
    fetch.mockImplementationOnce((url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    send();
    await act(async () => { await vi.advanceTimersByTimeAsync(110000); });
    expect(screen.getByText("The answer took too long. Please try again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry answer" }).disabled).toBe(false);
  });

  it("clears history immediately on replacement, including an invalid replacement", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok(answer));
    send();
    await screen.findByText(answerParagraph(answer.answer));
    choose("invalid.txt");
    expect(screen.queryByText(answerParagraph(answer.answer))).toBeNull();
    expect(screen.queryByText(question)).toBeNull();
    expect(screen.getByRole("textbox", { name: "Your question" }).disabled).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each([false, true])("ignores a previous document's late answer/error (reject=%s)", async (rejectOld) => {
    await openPaper();
    const old = deferred(), current = deferred();
    fetch.mockReturnValueOnce(old.promise);
    send("Old paper question");
    const oldSignal = fetch.mock.calls[2][1].signal;
    fetch.mockResolvedValueOnce(ok({ ...uploaded, document_id: "paper-two", preview: "Page 1\nReplacement preview" }));
    choose("second.pdf");
    await screen.findByText("Page 1 Replacement preview");
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryByText("Old paper question")).toBeNull();
    fetch.mockReturnValueOnce(current.promise);
    send("Current paper question");
    await act(async () => {
      if (rejectOld) old.reject(new TypeError("Old request failed"));
      else old.resolve(ok(answer));
    });
    expect(screen.queryByText(answerParagraph(answer.answer))).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Preparing answer…" }).disabled).toBe(true);
    await act(async () => current.resolve(ok({ ...answer, document_id: "paper-two" })));
    expect(screen.getByText(answerParagraph(answer.answer))).toBeTruthy();
    expect(screen.getByText("Page 1 Replacement preview")).toBeTruthy();
  });

  it("keeps only twelve turns and offers retry only for the most recent failure", async () => {
    await openPaper();
    for (let number = 0; number < 14; number += 1) {
      fetch.mockResolvedValueOnce(ok({ ...answer, answer: `Answer number ${number}. [Page 2]` }));
      send(`Question number ${number}`);
      await screen.findByText(answerParagraph(`Answer number ${number}. [Page 2]`));
    }
    const history = screen.getByRole("list", { name: "Conversation about the current paper" });
    expect(history.children).toHaveLength(12);
    expect(screen.queryByText("Question number 0")).toBeNull();
    fetch.mockResolvedValueOnce(failure("First failure"));
    send("Failed question one");
    await screen.findByText("First failure");
    fetch.mockResolvedValueOnce(failure("Second failure"));
    send("Failed question two");
    await screen.findByText("Second failure");
    expect(screen.getAllByRole("button", { name: "Retry answer" })).toHaveLength(1);
    expect(within(history.lastElementChild).getByRole("button", { name: "Retry answer" })).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Bug 2 regression: the browser must accept the same answers the backend accepts.
//
// The old rule rejected any page number written in ordinary prose, so a correct answer
// to "what does page 2 describe?" was refused twice: once by the backend (HTTP 502) and
// again here. If this validation were stricter than the backend's, the user would see an
// error for an answer the server had already approved.
// ---------------------------------------------------------------------------

describe("Prose page numbers alongside a valid citation", () => {
  it.each([
    "Page 2 describes the classifier accuracy of 93 percent. [Page 2]",
    "The description on page 2 covers the image classifier. [Page 2]",
    "As reported on page 2, accuracy is 93 percent. [Page 2]",
    "The measurement appears on p. 2 of the paper. [Page 2]",
    "Accuracy is 93 percent, which pp. 2 reports for the test dataset. [Page 2]",
  ])("accepts natural wording when that page is cited %#", async (answerText) => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok({ ...answer, answer: answerText }));
    send();
    await screen.findByText(answerParagraph(answerText));
    expect(screen.queryByText(/server returned an invalid answer/)).toBeNull();
    expect(screen.getByText("Supporting passages (1)")).toBeTruthy();
  });

  it("accepts prose naming two pages when both are cited", async () => {
    await openPaper();
    const answerText = "Pages 2 and 3 both discuss the classifier accuracy. [Page 2] [Page 3]";
    fetch.mockResolvedValueOnce(ok({
      ...answer,
      answer: answerText,
      sources: [
        answer.sources[0],
        { chunk_id: "chunk-2", page_number: 3, excerpt: "A second passage about the classifier." },
      ],
    }));
    send();
    await screen.findByText(answerParagraph(answerText));
    expect(screen.getByText("Supporting passages (2)")).toBeTruthy();
  });

  it.each([
    // A prose page reference with no bracketed citation at all.
    "Page 2 describes the classifier accuracy.",
    // Prose names a page the answer does not cite.
    "Page 99 describes the classifier accuracy. [Page 2]",
    "Accuracy is 93 percent, as p. 99 reports. [Page 2]",
    "See pages 99 for details. [Page 2]",
    // An imitation of the citation format is never a citation.
    "Claim about accuracy. [page 2]",
  ])("still rejects an unverifiable page reference %#", async (answerText) => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok({ ...answer, answer: answerText }));
    send();
    await screen.findByText(/server returned an invalid answer/);
    expect(screen.queryByText(answerParagraph(answerText))).toBeNull();
  });

  it("still rejects a cited page that is not among the returned sources", async () => {
    await openPaper();
    fetch.mockResolvedValueOnce(ok({
      ...answer,
      answer: "Page 2 describes the classifier. [Page 2] [Page 3]",
    }));
    send();
    await screen.findByText(/server returned an invalid answer/);
  });
});

describe("Citation navigation", () => {
  function mockPdf() {
    const renderPage = vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }));
    const getPage = vi.fn(async () => ({
      render: renderPage,
      getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }),
    }));
    const destroy = vi.fn(async () => {});
    openPdf.mockReset().mockReturnValue({ promise: Promise.resolve({ getPage }), destroy });
    return { getPage, renderPage, destroy };
  }

  it.each(["light", "dark"])("opens real page numbers from multiple answers in %s mode", async (theme) => {
    localStorage.setItem("paperlense-interface", JSON.stringify({ theme, language: "en", size: "large" }));
    const { getPage, destroy } = mockPdf();
    fetch.mockResolvedValueOnce(ok({ ...uploaded, page_count: 6 }));
    await openPaper();
    fetch.mockResolvedValueOnce(ok({
      ...answer,
      answer: "The study measured 42 samples. [Page 6] The aim appears on page 1. [Page 1]",
      sources: [
        { ...answer.sources[0], page_number: 6 },
        { chunk_id: "intro", page_number: 1, excerpt: "The study's aim." },
      ],
    }));
    send();
    const pageSix = await screen.findByRole("button", { name: "[Page 6]" });
    expect(screen.getAllByRole("button", { name: /^\[Page / })).toHaveLength(2);
    expect(pageSix.parentElement.textContent).toContain("The study measured 42 samples.");
    fireEvent.click(pageSix);
    const heading = screen.getByRole("heading", { name: "Selected page 6 of 6" });
    expect(document.activeElement).toBe(heading);
    await screen.findByRole("img", { name: "Original PDF page 6" });
    expect(getPage).toHaveBeenLastCalledWith(6);

    pageSix.focus();
    fireEvent.click(pageSix);
    expect(document.activeElement).toBe(heading);
    expect(openPdf).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "[Page 1]" }));
    await screen.findByRole("img", { name: "Original PDF page 1" });
    expect(getPage).toHaveBeenLastCalledWith(1);

    fetch.mockResolvedValueOnce(ok(answer));
    send("What else did the classifier report?");
    fireEvent.click(await screen.findByRole("button", { name: "[Page 2]" }));
    await screen.findByRole("img", { name: "Original PDF page 2" });
    expect(getPage).toHaveBeenLastCalledWith(2);
    expect(document.documentElement.dataset.theme).toBe(theme);
    expect(document.documentElement.dataset.textSize).toBe("large");

    fetch.mockResolvedValueOnce(ok({ ...uploaded, document_id: "new-paper", preview: "Replacement PDF" }));
    choose("new.pdf");
    await screen.findByText("Replacement PDF");
    fireEvent.click(pageSix);
    expect(screen.queryByRole("button", { name: "[Page 6]" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Selected page/ })).toBeNull();
    expect(destroy).toHaveBeenCalledOnce();
    expect(getPage).toHaveBeenCalledTimes(3);
  });

  it.each(["open", "render"])("reports a PDF %s failure without removing extracted text", async (failure) => {
    const { renderPage } = mockPdf();
    if (failure === "open") openPdf.mockImplementationOnce(() => ({
      promise: Promise.reject(new Error("invalid PDF")), destroy: vi.fn(async () => {}),
    }));
    else renderPage.mockImplementationOnce(() => ({
      promise: Promise.reject(new Error("render failure")), cancel: vi.fn(),
    }));
    fetch.mockResolvedValueOnce(ok({ ...uploaded, page_count: 1 }));
    await openPaper();
    fetch.mockResolvedValueOnce(ok({
      ...answer, answer: "This PDF has one page. [Page 1]",
      sources: [{ ...answer.sources[0], page_number: 1 }],
    }));
    send();
    fireEvent.click(await screen.findByRole("button", { name: "[Page 1]" }));
    expect(screen.getByRole("heading", { name: "Selected page 1 of 1" })).toBeTruthy();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/could not be (opened|displayed)/);
    expect(screen.getByText("Page 2 Classifier research preview")).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Original PDF page 1" })).toBeNull();
  });

  it("opens the supporting passage's page in a one-page PDF", async () => {
    const { getPage } = mockPdf();
    fetch.mockResolvedValueOnce(ok({ ...uploaded, page_count: 1 }));
    await openPaper();
    fetch.mockResolvedValueOnce(ok({
      ...answer, answer: "The study reports 93 percent accuracy. [Page 1]",
      sources: [{ ...answer.sources[0], page_number: 1 }],
    }));
    send();
    fireEvent.click(await screen.findByText("Supporting passages (1)"));
    fireEvent.click(screen.getByRole("button", { name: "Page 1", exact: true }));
    await screen.findByRole("img", { name: "Original PDF page 1" });
    expect(getPage).toHaveBeenCalledExactlyOnceWith(1);
  });
});
