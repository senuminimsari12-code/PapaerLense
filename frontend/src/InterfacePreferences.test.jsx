import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import App from "./App.jsx";

// Citation buttons split the text into nodes; compare the whole answer paragraph.
const answerParagraph = (text) => (_content, node) =>
  node.matches("p.message-text") && node.textContent === text;

const storageKey = "paperlense-interface";
const root = document.documentElement;

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  root.removeAttribute("data-theme");
  root.removeAttribute("data-text-size");
  root.lang = "en";
  vi.unstubAllGlobals();
});

function select(name, value) {
  fireEvent.change(screen.getByRole("combobox", { name }), { target: { value } });
}

function upload() {
  fireEvent.change(screen.getByLabelText("Choose a research paper PDF"), {
    target: { files: [new File(["pdf bytes"], "study.pdf", { type: "application/pdf" })] },
  });
}

const ok = (data) => ({ ok: true, json: async () => data });

describe("Interface preferences", () => {
  it("defaults to light, English, and medium", () => {
    render(<App />);
    expect(root.dataset.theme).toBe("light");
    expect(root.lang).toBe("en");
    expect(root.dataset.textSize).toBe("medium");
    expect(screen.getByRole("combobox", { name: "Text size" }).value).toBe("medium");
    expect(screen.getByRole("button", { name: /switch to dark mode/i })).toBeTruthy();
  });

  it("uses the system theme for an invalid saved preference and can switch both ways", () => {
    matchMedia.mockReturnValue({ matches: true });
    localStorage.setItem(storageKey, '{"theme":"invalid","language":"xx","size":"huge"}');
    render(<App />);
    expect(matchMedia).toHaveBeenCalledWith("(prefers-color-scheme: dark)");
    expect(root.dataset.theme).toBe("dark");
    expect(root.lang).toBe("en");
    expect(root.dataset.textSize).toBe("medium");
    fireEvent.click(screen.getByRole("button", { name: /switch to light mode/i }));
    expect(root.dataset.theme).toBe("light");
    fireEvent.click(screen.getByRole("button", { name: /switch to dark mode/i }));
    expect(root.dataset.theme).toBe("dark");
  });

  it("restores all three settings together after remount and switches all three languages", () => {
    localStorage.setItem(storageKey, "{broken");
    const firstVisit = render(<App />);
    select("Text size", "small");
    expect(root.dataset.textSize).toBe("small");
    select("Text size", "medium");
    expect(root.dataset.textSize).toBe("medium");
    fireEvent.click(screen.getByRole("button", { name: /switch to dark mode/i }));
    select("Language", "si");
    select("අකුරු ප්‍රමාණය", "large");
    expect(root.lang).toBe("si");
    expect(screen.getByRole("button", { name: "PDF ගොනුව තෝරන්න" })).toBeTruthy();
    firstVisit.unmount();

    render(<App />);
    expect(root.dataset.theme).toBe("dark");
    expect(root.lang).toBe("si");
    expect(root.dataset.textSize).toBe("large");
    select("භාෂාව", "ta");
    expect(root.lang).toBe("ta");
    expect(screen.getByRole("button", { name: "PDF கோப்பைத் தேர்ந்தெடுக்கவும்" })).toBeTruthy();
    expect(screen.getByPlaceholderText("இந்தக் கட்டுரையைப் பற்றி என்ன தெரிந்துகொள்ள விரும்புகிறீர்கள்?")).toBeTruthy();
    select("மொழி", "en");
    expect(root.lang).toBe("en");
    expect(screen.getByRole("button", { name: "Choose PDF" })).toBeTruthy();
  });

  it("keeps the loaded PDF, automatic summary, draft, answer, and evidence when settings change", async () => {
    const question = "මිනුම කුමක්ද?";
    const answer = "The study measured temperature. [Page 1]";
    const excerpt = "The temperature was measured hourly.";
    fetch.mockResolvedValueOnce(ok({
      document_id: "study", filename: "study.pdf", page_count: 1, character_count: 42,
      preview: "Page 1\nUnchanged paper preview",
    })).mockResolvedValueOnce(ok({
      document_id: "study", model: "test-model", source_page_count: 1, source_character_count: 42,
      summary: {
        title_authors_abstract: "Original abstract", problem_statement: "Original problem",
        methodology: "Original methods", key_results: "Original results", conclusion: "Original conclusion",
      },
    })).mockResolvedValueOnce(ok({
      document_id: "study", answer, model: "test-model", insufficient_evidence: false,
      sources: [{ chunk_id: "chunk-1", page_number: 1, excerpt }],
    }));

    render(<App />);
    upload();
    await screen.findByText("Original methods");
    fireEvent.change(screen.getByRole("textbox", { name: "Your question" }), { target: { value: question } });
    select("Language", "ta");
    expect(screen.getByRole("textbox", { name: "உங்கள் கேள்வி" }).value).toBe(question);
    fireEvent.submit(screen.getByRole("textbox", { name: "உங்கள் கேள்வி" }).form);
    await screen.findByText(answerParagraph(answer));
    expect(fetch.mock.calls[1][0]).toMatch(/\/documents\/study\/summary$/);
    expect(fetch.mock.calls[2][0]).toMatch(/\/documents\/study\/chat$/);
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ question });

    fireEvent.click(within(screen.getByRole("group", { name: "இடைமுக அமைப்புகள்" })).getByRole("button"));
    select("எழுத்தளவு", "large");
    select("மொழி", "si");
    expect(screen.getByText("Page 1 Unchanged paper preview")).toBeTruthy();
    expect(screen.getByText("study.pdf")).toBeTruthy();
    for (const section of ["abstract", "problem", "methods", "results", "conclusion"]) {
      expect(screen.getByText("Original " + section)).toBeTruthy();
    }
    expect(screen.getByText(question)).toBeTruthy();
    expect(screen.getByText(answerParagraph(answer))).toBeTruthy();
    expect(screen.getByText(excerpt)).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(JSON.parse(localStorage.getItem(storageKey))).toEqual({
      theme: "dark", language: "si", size: "large",
    });
  });

  it("translates an existing upload error when the language changes", async () => {
    const detail = "This PDF is password-protected. Upload an unlocked copy.";
    fetch.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail }) });
    render(<App />);
    upload();
    await screen.findByText(detail);
    select("Language", "ta");
    expect(screen.getByRole("alert").textContent).toContain("கடவுச்சொல்லால் பாதுகாக்கப்பட்டுள்ளது");
    expect(screen.queryByText(detail)).toBeNull();
    expect(fetch).toHaveBeenCalledOnce();
  });
});
