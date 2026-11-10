import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import App, { formatFileSize } from "./App.jsx";

const successfulResult = {
  session_id: "s".repeat(43),
  document_id: "document-one",
  filename: "first.pdf",
  page_count: 3,
  character_count: 42,
  preview: "Page 1\nOriginal research preview",
};

function choose(name = "first.pdf", data = "pdf bytes") {
  const file = new File([data], name, { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("Choose a research paper PDF"), {
    target: { files: [file] },
  });
  return file;
}

async function uploadFirstDocument() {
  choose();
  await screen.findByText("Page 1 Original research preview");
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) => Promise.resolve(url.endsWith("/summary")
      ? summarySuccess({ ...summaryResult, document_id: url.split("/").at(-2) })
      : { ok: true, json: async () => successfulResult })),
  );
});
afterEach(() => {
  sessionStorage.clear();
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PaperLense upload flow", () => {
  it("starts with an honest empty state and planned features", () => {
    render(<App />);
    expect(screen.getByText("Awaiting your paper")).toBeTruthy();
    expect(screen.queryByText("Planned")).toBeNull();
    expect(screen.getAllByText("Available")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Generate Summary" }).disabled,
    ).toBe(true);
    expect(screen.queryByLabelText("Extracted text preview")).toBeNull();
  });

  it("opens the file picker through the visible button", () => {
    render(<App />);
    const input = screen.getByLabelText("Choose a research paper PDF");
    const click = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: "Choose PDF" }));
    expect(click).toHaveBeenCalledOnce();
  });

  it("sends FormData and displays only actual API results", async () => {
    render(<App />);
    const file = choose();
    await screen.findByText("Page 1 Original research preview");
    expect(screen.getByText("3", { selector: "dd" })).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.getByText("first.pdf")).toBeTruthy();
    expect(screen.getByText(/9 bytes/)).toBeTruthy();
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/upload");
    expect(options.body.get("file")).toBe(file);
    expect(options.headers).toBeUndefined();
  });

  it("keeps the header help link usable after the empty-state introduction is removed", async () => {
    render(<App />);
    await uploadFirstDocument();
    expect(screen.queryByRole("heading", { name: "Research paper workspace" })).toBeNull();
    const helpLink = screen.getByRole("link", { name: /how it works/i });
    expect(document.querySelector(helpLink.getAttribute("href"))).toBeTruthy();
  });

  it("clears old text immediately and prevents repeated submissions while processing", async () => {
    render(<App />);
    await uploadFirstDocument();
    let finish;
    fetch.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    choose("second.pdf");
    expect(screen.queryByText("Page 1 Original research preview")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Processing PDF" }).disabled,
    ).toBe(true);
    const zone = screen
      .getByText("Bringing your paper into focus…")
      .closest(".drop-zone");
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(["x"], "third.pdf")] },
    });
    expect(fetch).toHaveBeenCalledTimes(3); // First upload + automatic summary + replacement upload.
    finish({
      ok: true,
      json: async () => ({
        ...successfulResult,
        filename: "second.pdf",
        preview: "Page 1\nNew paper preview",
      }),
    });
    await screen.findByText("Page 1 New paper preview");
  });

  it("clears stale results when a replacement fails on the server", async () => {
    render(<App />);
    await uploadFirstDocument();
    fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "This PDF is password-protected." }),
    });
    choose("locked.pdf");
    await screen.findByRole("alert");
    expect(screen.getByText("This PDF is password-protected.")).toBeTruthy();
    expect(screen.queryByText("Page 1 Original research preview")).toBeNull();
    expect(screen.queryByText("Processed successfully")).toBeNull();
    expect(screen.getByText("Awaiting your paper")).toBeTruthy();
  });

  it.each([
    ["notes.txt", "text", "Other document formats"],
    ["empty.pdf", "", "This file is empty"],
  ])(
    "clears stale results when %s fails client validation",
    async (name, data, message) => {
      render(<App />);
      await uploadFirstDocument();
      choose(name, data);
      expect(screen.getByRole("alert").textContent).toContain(message);
      expect(screen.queryByText("Page 1 Original research preview")).toBeNull();
      expect(fetch).toHaveBeenCalledTimes(2); // No requests beyond the initial upload/summary.
    },
  );

  it("rejects oversized files before sending them", () => {
    render(<App />);
    const file = new File(["x"], "large.pdf");
    Object.defineProperty(file, "size", { value: 20 * 1024 * 1024 + 1 });
    fireEvent.change(screen.getByLabelText("Choose a research paper PDF"), {
      target: { files: [file] },
    });
    expect(screen.getByRole("alert").textContent).toContain("20 MiB");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("accepts a single dropped PDF", async () => {
    render(<App />);
    const zone = screen
      .getByText("Drop your research paper here")
      .closest(".drop-zone");
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(["x"], "dropped.pdf")] },
    });
    await screen.findByText("Page 1 Original research preview");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("rejects multiple dropped files and removes the previous preview", async () => {
    render(<App />);
    await uploadFirstDocument();
    const zone = screen.getByText("Your paper is ready").closest(".drop-zone");
    fireEvent.drop(zone, {
      dataTransfer: {
        files: [new File(["x"], "one.pdf"), new File(["x"], "two.pdf")],
      },
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "one PDF at a time",
    );
    expect(screen.queryByText("Page 1 Original research preview")).toBeNull();
  });

  it("handles a network failure without retaining old results", async () => {
    render(<App />);
    await uploadFirstDocument();
    fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    choose("offline.pdf");
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain(
      "backend is running",
    );
    expect(screen.queryByText("Page 1 Original research preview")).toBeNull();
  });

  it("aborts a timed-out upload and accepts a retry without a duplicate summary", async () => {
    vi.useFakeTimers();
    fetch.mockImplementationOnce((_url, { signal }) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }),
    );
    render(<App />);
    choose();
    expect(screen.getByRole("button", { name: "Processing PDF" }).disabled).toBe(true);

    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });

    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Processing took too long.");
    expect(screen.getByRole("button", { name: "Choose another PDF" }).disabled).toBe(false);
    expect(screen.queryByLabelText("Extracted text preview")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);

    await act(async () => { choose(); });
    expect(screen.getByText("Page 1 Original research preview")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
      "/api/upload", "/api/upload", "/api/documents/document-one/summary",
    ]);
  });

  it("rejects incomplete server success responses", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ document_id: "missing fields" }),
    });
    render(<App />);
    choose();
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain(
      "incomplete result",
    );
    expect(screen.queryByLabelText("Extracted text preview")).toBeNull();
  });

  it("handles non-JSON error responses and permits retrying the same filename", async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    });
    render(<App />);
    choose();
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain(
      "unreadable response",
    );
    choose();
    await screen.findByText("Page 1 Original research preview");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports an HTTP upload failure when the JSON error body is null", async () => {
    fetch.mockResolvedValueOnce({ ok: false, json: async () => null });
    render(<App />);
    choose();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The PDF could not be processed.");
    expect(screen.queryByLabelText("Extracted text preview")).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

it("formats byte, KB and MB sizes for people", () => {
  expect(formatFileSize(100)).toBe("100 bytes");
  expect(formatFileSize(2048)).toBe("2.0 KB");
  expect(formatFileSize(1572864)).toBe("1.5 MB");
});

const summaryResult = {
  document_id: "document-one",
  model: "test-model",
  source_page_count: 3,
  source_character_count: 42,
  summary: {
    title_authors_abstract:
      "Fixture paper by Example Author. The abstract describes a test.",
    problem_statement: "A specific fixture research question.",
    methodology: "The paper reports a controlled comparison.",
    key_results: "The fixture reports an improvement of 2 points.",
    conclusion: "The authors limit their conclusion to this dataset.",
  },
};

function summarySuccess(result = summaryResult) {
  return { ok: true, json: async () => result };
}

async function showSummary() {
  await screen.findByText(summaryResult.summary.key_results);
}

function mockInitialSummary(response) {
  // Queue the upload response before the automatically chained summary response.
  fetch.mockResolvedValueOnce({ ok: true, json: async () => successfulResult })
    .mockResolvedValueOnce(response);
}

describe("PaperLense structured summaries", () => {
  it("automatically generates after upload and renders all five sections in order", async () => {
    render(<App />);
    await uploadFirstDocument();
    await showSummary();
    const summaryRegion = screen.getByRole("region", {
      name: "Your paper, understood",
    });
    const headings = within(summaryRegion).getAllByRole("heading", {
      level: 3,
    });
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "Title & Authors and Abstract",
      "Problem Statement",
      "Methodology",
      "Key Results",
      "Conclusion",
    ]);
    expect(screen.getByText(/Summary generated for first.pdf/)).toBeTruthy();
    expect(
      screen.getByText(/AI-generated from extracted text using test-model/),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Generate Summary" }),
    ).toBeNull();
    const [url, options] = fetch.mock.calls[1];
    expect(url).toBe(
      "http://localhost:8000/api/documents/document-one/summary",
    );
    expect(options.method).toBe("POST");
    expect(options.body).toBeUndefined();
    expect(options.headers).toEqual({ "X-PaperLens-Session": successfulResult.session_id });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("shows loading and prevents a duplicate summary request", async () => {
    let finish;
    mockInitialSummary(new Promise((resolve) => { finish = resolve; }));
    render(<App />);
    await uploadFirstDocument();
    const button = screen.getByRole("button", { name: "Generating summary…" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(
      screen.getByRole("button", { name: "Generating summary…" }).disabled,
    ).toBe(true);
    expect(
      screen.getByText(/Generating a summary from the extracted text/),
    ).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => {
      finish(summarySuccess());
    });
    await screen.findByText(summaryResult.summary.key_results);
  });

  it("preserves the uploaded paper after an error and supports retry", async () => {
    mockInitialSummary({
      ok: false,
      json: async () => ({
        detail: "Set GEMINI_API_KEY in the backend and restart it.",
      }),
    });
    render(<App />);
    await uploadFirstDocument();
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("GEMINI_API_KEY");
    expect(screen.getByText("Page 1 Original research preview")).toBeTruthy();
    fetch.mockResolvedValueOnce(summarySuccess());
    fireEvent.click(screen.getByRole("button", { name: "Retry summary" }));
    await screen.findByText(summaryResult.summary.key_results);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears a previous summary immediately when another document is selected", async () => {
    render(<App />);
    await uploadFirstDocument();
    await showSummary();
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...successfulResult,
        document_id: "document-two",
        filename: "second.pdf",
        preview: "Second paper text",
      }),
    });
    choose("second.pdf");
    expect(screen.queryByText(summaryResult.summary.key_results)).toBeNull();
    await screen.findByText("Second paper text");
    await screen.findByText(/Summary generated for second.pdf/);
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/summary"))).toHaveLength(2);
  });

  it.each([
    ["notes.txt", "text"],
    ["broken.pdf", "bad bytes"],
  ])(
    "clears a previous summary even if replacement %s is rejected",
    async (filename, data) => {
      render(<App />);
      await uploadFirstDocument();
      await showSummary();
      fetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: "This file is not a PDF." }),
      });
      choose(filename, data);
      await screen.findByRole("alert");
      expect(screen.queryByText(summaryResult.summary.key_results)).toBeNull();
      expect(
        screen.getByRole("button", { name: "Generate Summary" }).disabled,
      ).toBe(true);
    },
  );

  it.each(["success", "failure"])(
    "ignores an old request's late %s without unlocking a newer request",
    async (outcome) => {
      let finishOld;
      let failOld;
      mockInitialSummary(new Promise((resolve, reject) => {
        finishOld = resolve;
        failOld = reject;
      }));
      render(<App />);
      await uploadFirstDocument();
      const oldSignal = fetch.mock.calls[1][1].signal;
      let finishNew;
      fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ...successfulResult,
          document_id: "document-two",
          filename: "second.pdf",
          preview: "Second paper text",
        }),
      }).mockResolvedValueOnce(new Promise((resolve) => { finishNew = resolve; }));
      choose("second.pdf");
      await screen.findByText("Second paper text");
      expect(oldSignal.aborted).toBe(true);
      await act(async () => {
        if (outcome === "success") finishOld(summarySuccess());
        else failOld(new Error("Stale provider failure"));
      });
      expect(screen.queryByText(summaryResult.summary.key_results)).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(
        screen.getByRole("button", { name: "Generating summary…" }).disabled,
      ).toBe(true);
      await act(async () => {
        finishNew(
          summarySuccess({ ...summaryResult, document_id: "document-two" }),
        );
      });
      await screen.findByText(summaryResult.summary.key_results);
      expect(screen.getByText(/Summary generated for second.pdf/)).toBeTruthy();
      expect(fetch).toHaveBeenCalledTimes(4);
    },
  );

  it.each([
    [
      { ...summaryResult, summary: { conclusion: "Only one section" } },
      "incomplete summary",
    ],
    [{ ...summaryResult, document_id: "wrong-document" }, "incomplete summary"],
    [
      {
        ...summaryResult,
        summary: { ...summaryResult.summary, methodology: "  " },
      },
      "incomplete summary",
    ],
    [null, "incomplete summary"],
  ])(
    "rejects incomplete or mismatched successful responses",
    async (result, message) => {
      mockInitialSummary(summarySuccess(result));
      render(<App />);
      await uploadFirstDocument();
      await screen.findByRole("alert");
      expect(screen.getByRole("alert").textContent).toContain(message);
      expect(screen.queryByText(summaryResult.summary.key_results)).toBeNull();
    },
  );

  it("handles network and non-JSON errors without losing the extracted preview", async () => {
    fetch.mockResolvedValueOnce({ ok: true, json: async () => successfulResult })
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<App />);
    await uploadFirstDocument();
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain(
      "backend connection",
    );
    fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => {
        throw new SyntaxError("Bad JSON");
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Retry summary" }));
    await screen.findByText(/unreadable summary response/);
    expect(screen.getByText("Page 1 Original research preview")).toBeTruthy();
  });

  it("aborts a summary that exceeds the browser deadline and permits retry", async () => {
    render(<App />);
    vi.useFakeTimers();
    fetch.mockResolvedValueOnce({ ok: true, json: async () => successfulResult }).mockImplementationOnce(
      (url, { signal }) =>
        new Promise((resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    await act(async () => { choose(); });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(110_000);
    });
    expect(screen.getByRole("alert").textContent).toContain("took too long");
    expect(screen.getByRole("button", { name: "Retry summary" }).disabled).toBe(
      false,
    );
  });
});
