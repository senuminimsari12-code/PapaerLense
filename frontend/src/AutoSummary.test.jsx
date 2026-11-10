import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App.jsx";

const paper = { session_id: "s".repeat(43), document_id: "accepted-paper", filename: "paper.pdf", page_count: 2,
  character_count: 80, preview: "Accepted research preview" };
const summary = {
  document_id: paper.document_id, model: "mock-model", source_page_count: 2,
  source_character_count: 80, summary: {
    title_authors_abstract: "Test paper, authors and abstract.", problem_statement: "A research problem.",
    methodology: "A controlled experiment.", key_results: "The classifier scored 93 percent.",
    conclusion: "A limited conclusion.",
  },
};
const answer = { document_id: paper.document_id, answer: "Accuracy was 93 percent. [Page 1]",
  sources: [{ chunk_id: "chunk-1", page_number: 1, excerpt: "Classifier accuracy was 93 percent." }],
  insufficient_evidence: false, context_question: null, model: "mock-model" };
const ok = (data) => ({ ok: true, json: async () => data });
const failure = (detail) => ({ ok: false, json: async () => ({ detail }) });
const summaries = () => fetch.mock.calls.filter(([url]) => url.endsWith("/summary"));

function choose(name = "paper.pdf", data = "pdf bytes") {
  const file = new File([data], name, { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("Choose a research paper PDF"), { target: { files: [file] } });
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((url) => {
    if (url.endsWith("/api/upload")) return Promise.resolve(ok(paper));
    if (url.endsWith("/summary")) return Promise.resolve(ok(summary));
    if (url.endsWith("/chat")) return Promise.resolve(ok(answer));
    throw new Error("Unexpected API URL in test");
  }));
});
afterEach(() => { sessionStorage.clear(); cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("automatically starts exactly one summary in Strict Mode after upload acceptance", async () => {
  const upload = deferred();
  fetch.mockReturnValueOnce(upload.promise);
  render(<React.StrictMode><App /></React.StrictMode>);
  choose();
  expect(summaries()).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Generate Summary" }).disabled).toBe(true);
  await act(async () => upload.resolve(ok(paper)));
  await screen.findByText(summary.summary.key_results);
  expect(summaries()).toHaveLength(1);
  const [url, options] = summaries()[0];
  expect(url).toBe("http://localhost:8000/api/documents/accepted-paper/summary");
  expect(options.method).toBe("POST");
  expect(options.body).toBeUndefined();
  expect(options.headers).toEqual({ "X-PaperLens-Session": paper.session_id });
  expect(screen.getByText(paper.preview)).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), { target: { value: "typing" } });
  expect(summaries()).toHaveLength(1);
});

it.each([["notes.txt", "text"], ["empty.pdf", ""]])("does not summarize rejected client upload %s", (name, data) => {
  render(<App />); choose(name, data);
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
});

it("asks for another upload when a session expires and uses the new token after reupload", async () => {
  const renewed = { ...paper, document_id: "fresh-document", session_id: "r".repeat(43) };
  fetch
    .mockResolvedValueOnce(ok(paper))
    .mockResolvedValueOnce({
      ok: false, status: 404,
      json: async () => ({ detail: "This document is no longer available. Upload the PDF again." }),
    })
    .mockResolvedValueOnce(ok(renewed))
    .mockResolvedValueOnce(ok({ ...summary, document_id: renewed.document_id }));

  const firstVisit = render(<App />);
  choose();
  await screen.findByText(/Upload the PDF again/);
  firstVisit.unmount();
  render(<App />);
  choose();
  await screen.findByText(summary.summary.key_results);
  expect(fetch.mock.calls[2][1].headers).toEqual({ "X-PaperLens-Session": paper.session_id });
  expect(fetch.mock.calls[3][1].headers).toEqual({ "X-PaperLens-Session": renewed.session_id });
});

it.each([
  failure("This PDF is corrupted."),
  ok({ document_id: "missing-metadata" }),
  ok({ ...paper, document_id: 123 }),
  ok({ ...paper, document_id: "   " }),
])("does not summarize a failed or invalid upload response %#", async (response) => {
  fetch.mockResolvedValueOnce(response);
  render(<App />); choose();
  await screen.findByRole("alert");
  expect(summaries()).toHaveLength(0);
  expect(screen.queryByLabelText("Extracted text preview")).toBeNull();
});

it("shows automatic loading and rejects repeated manual clicks during generation", async () => {
  const pending = deferred();
  fetch.mockResolvedValueOnce(ok(paper)).mockReturnValueOnce(pending.promise);
  render(<App />); choose();
  await screen.findByText(paper.preview);
  const button = screen.getByRole("button", { name: "Generating summary…" });
  expect(button.disabled).toBe(true);
  const summaryStatus = screen.getByText(/You can ask questions about your paper while you wait/)
    .closest('[role="status"]');
  expect(summaryStatus).not.toBeNull();
  expect(summaryStatus.closest('[aria-busy="true"]')).toBeNull();
  expect(screen.getByRole("textbox", { name: "Your question" }).disabled).toBe(false);
  fireEvent.click(button); fireEvent.click(button);
  expect(summaries()).toHaveLength(1);
  await act(async () => pending.resolve(ok(summary)));
  expect(screen.getByText("Summary ready")).toBeTruthy();
});

it("retries only on explicit action, targets the current document and guards double retry", async () => {
  fetch.mockResolvedValueOnce(ok(paper)).mockResolvedValueOnce(failure("Provider unavailable."));
  render(<App />); choose();
  await screen.findByText("Provider unavailable.");
  expect(screen.getByText(paper.preview)).toBeTruthy();
  expect(summaries()).toHaveLength(1);
  const retry = deferred();
  fetch.mockReturnValueOnce(retry.promise);
  const button = screen.getByRole("button", { name: "Retry summary" });
  fireEvent.click(button); fireEvent.click(button);
  expect(summaries()).toHaveLength(2);
  expect(summaries()[1][0]).toBe(summaries()[0][0]);
  await act(async () => retry.resolve(failure("Still unavailable.")));
  await screen.findByText("Still unavailable.");
  fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), { target: { value: "Another question" } });
  expect(summaries()).toHaveLength(2);
});

it("reports a summary failure with a null JSON body and keeps the paper", async () => {
  fetch.mockResolvedValueOnce(ok(paper))
    .mockResolvedValueOnce({ ok: false, json: async () => null });
  render(<App />);
  choose();
  await screen.findByText(/The summary could not be generated/);
  expect(screen.getByText(paper.preview)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Retry summary" })).toBeTruthy();
  expect(summaries()).toHaveLength(1);
});

it("retry after replacement targets only the current document", async () => {
  fetch.mockResolvedValueOnce(ok(paper)).mockResolvedValueOnce(failure("First summary failed."));
  render(<App />); choose();
  await screen.findByText("First summary failed.");
  const second = { ...paper, document_id: "second-paper", filename: "second.pdf" };
  fetch.mockResolvedValueOnce(ok(second)).mockResolvedValueOnce(failure("Second summary failed."));
  choose("second.pdf");
  await screen.findByText("Second summary failed.");
  expect(screen.queryByText("First summary failed.")).toBeNull();
  fetch.mockResolvedValueOnce(ok({ ...summary, document_id: second.document_id }));
  fireEvent.click(screen.getByRole("button", { name: "Retry summary" }));
  await screen.findByText(/Summary generated for second.pdf/);
  expect(summaries().map(([url]) => url)).toEqual([
    "http://localhost:8000/api/documents/accepted-paper/summary",
    "http://localhost:8000/api/documents/second-paper/summary",
    "http://localhost:8000/api/documents/second-paper/summary",
  ]);
});

it.each([["client", "success"], ["client", "failure"], ["server", "success"], ["server", "failure"]])(
  "a rejected %s replacement cancels automatic generation and ignores a late %s", async (kind, outcome) => {
    const old = deferred();
    fetch.mockResolvedValueOnce(ok(paper)).mockReturnValueOnce(old.promise);
    render(<App />); choose();
    await screen.findByText(paper.preview);
    const signal = summaries()[0][1].signal;
    if (kind === "server") fetch.mockResolvedValueOnce(failure("Corrupted replacement."));
    choose(kind === "client" ? "notes.txt" : "bad.pdf");
    await screen.findByRole("alert");
    expect(signal.aborted).toBe(true);
    await act(async () => {
      if (outcome === "success") old.resolve(ok(summary));
      else old.reject(new Error("Old summary failure"));
    });
    expect(screen.queryByText(summary.summary.key_results)).toBeNull();
    expect(screen.queryByText(paper.preview)).toBeNull();
    expect(screen.getByRole("button", { name: "Generate Summary" }).disabled).toBe(true);
    expect(screen.queryByText("Old summary failure")).toBeNull();
    expect(summaries()).toHaveLength(1);
  });

it.each(["success", "failure"])("Q&A works during and after an automatic summary %s", async (outcome) => {
  const pending = deferred();
  fetch.mockResolvedValueOnce(ok(paper)).mockReturnValueOnce(pending.promise);
  render(<App />); choose();
  await screen.findByText(paper.preview);
  const input = screen.getByRole("textbox", { name: "Your question" });
  expect(input.disabled).toBe(false);
  fireEvent.change(input, { target: { value: "What accuracy was measured?" } });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText((_content, node) =>
    node.matches("p.message-text") && node.textContent === answer.answer);
  expect(screen.getByRole("button", { name: "Generating summary…" }).disabled).toBe(true);
  await act(async () => pending.resolve(outcome === "success" ? ok(summary) : failure("Summary unavailable.")));
  if (outcome === "success") await screen.findByText(summary.summary.key_results);
  else await screen.findByText("Summary unavailable.");
  fireEvent.change(input, { target: { value: "Explain the classifier accuracy." } });
  fireEvent.click(screen.getByRole("button", { name: "Send question" }));
  await screen.findByText("Explain the classifier accuracy.");
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/chat"))).toHaveLength(2);
  expect(summaries()).toHaveLength(1);
});

it("an expired document produces an honest error without an automatic retry", async () => {
  fetch.mockResolvedValueOnce(ok(paper)).mockResolvedValueOnce(failure("This document is no longer available. Upload the PDF again."));
  render(<App />); choose();
  await screen.findByText(/This document is no longer available/);
  expect(screen.queryByText(summary.summary.key_results)).toBeNull();
  expect(summaries()).toHaveLength(1);
  expect(screen.getByText(paper.preview)).toBeTruthy();
});
