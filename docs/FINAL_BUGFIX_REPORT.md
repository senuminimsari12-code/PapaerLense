# PaperLense — Final Three-Bug Fix Report

**Date:** 2026-11-08
**Branch:** `codex/multi-provider-failover`
**Baseline commit:** `9fe8bc8` (the readability refactor is still uncommitted and was preserved)

**Results:** backend 196 → **241 passed**, frontend 73 → **85 passed**, production build **passed**.
All three bugs were verified **live** against real AI providers. Nothing was committed.

---

## 1. The three original bugs

| # | Bug | Symptom | Priority |
|---|---|---|---|
| 1 | Generic research questions retrieved nothing | "Not enough evidence" for questions whose answer is plainly in the paper | HIGH |
| 2 | Page-specific questions failed | HTTP 502 even when the AI answered correctly with a valid `[Page 6]` citation | HIGH |
| 3 | Groq HTTP 413 misclassified | A paper too large for Groq was reported as a configuration/model error | MEDIUM |

---

## 2. Bug 1 — generic questions retrieved nothing

### What was actually wrong

Measured against the real 15-page *Attention Is All You Need* paper and the 16-page *BERT*
paper, before any change:

| Question | Chunks found | Why |
|---|---|---|
| What is the main topic of this paper? | **0** | "topic" never appears in a research paper |
| What research problem does this paper address? | **0** | "address" never appears either |
| What methodology did the authors use to train the model? | **0** | best passage scored **0.0935**, just under the 0.12 threshold |
| What do the authors conclude? | **0** | neither "author" nor "conclude" appears; score was exactly **0.0** |

So there were really **two different causes**, not one:

- **A vocabulary gap.** TF-IDF compares words, not meaning. The paper says "Conclusion"
  and "findings"; the question says "conclude". Zero shared words means zero score, and
  no threshold change can fix that.
- **A threshold that was slightly too high.** The methodology question *did* find the
  right passages — 13 of them passed the word checks — and then every one was thrown away
  for scoring under `MIN_SIMILARITY = 0.12`.

### What was changed

Three small rules in `backend/retrieval.py`. TF-IDF, cosine similarity, chunking, page
numbers, the four-passage limit and the RAG architecture are all unchanged.

**1. `RELATED_PAPER_WORDS` + `add_related_words()`** — a plain dictionary mapping a
question word to the words papers actually use. "conclude" also searches for
"conclusion", "finding" and "result"; "method" also searches for "approach",
"experiment", "training" and "architecture". Added words get a count of 1 so they act as
hints without outweighing what the user typed.

**2. `OVERVIEW_PHRASES` + `asks_for_paper_overview()`** — whole-paper questions go
straight to the opening chunks. This mirrors the title shortcut that was already in the
file, and for the same reason: the words that make "what is the main topic of this paper?"
meaningful are not in the paper, but the abstract answers it. Every phrase mentions the
paper or the document, so unrelated questions cannot match by accident.

**3. A second attempt at a lower score** — `FALLBACK_MIN_SIMILARITY = 0.05`,
returning at most `FALLBACK_MAX_CHUNKS = 3`. It runs **only** when the normal search
found nothing, and it only reconsiders chunks that had **already passed the word checks**.
That is the important part: it lowers the score bar without lowering the relevance bar.

### The safety guard, and why it was necessary

A fallback on score alone would have been unsafe. Measuring the BERT paper,
*"What is the weather like in Paris today?"* scores **0.1304** — higher than the
methodology question we wanted to rescue. It is correctly rejected today only because it
matches **1 of 4** question words, failing the word checks.

So `question_names_something_absent()` was added as a gate on both relaxations: if the
question names a subject the paper never mentions, the strict rules stay in force.
General research words ("method", "conclude", "author", "page") are ignored by this
check, which is what lets "what do the authors conclude?" still count as a real question
about the paper.

This specifically protects the existing test asserting that *"method for baking
croissants"* returns nothing: "method" is a general word the paper does use, but
"croissant" is a subject it never mentions, so the relaxations stay switched off.

### Functions added or changed in `backend/retrieval.py`

| Function | Status | Purpose |
|---|---|---|
| `asks_for_paper_overview` | new | Is this a question about the paper as a whole? |
| `question_names_something_absent` | new | Does the question name a subject the paper never mentions? |
| `add_related_words` | new | Add the words a paper would really use |
| `find_matching_chunks` | new | Score every chunk that shares enough words (lifted out of `retrieve_chunks`) |
| `select_best_chunks` | new | Sort, drop repeats, apply the limit (lifted out of `retrieve_chunks`) |
| `retrieve_chunks` | changed | Now reads as four numbered steps |

`find_matching_chunks` and `select_best_chunks` are not new logic — they are the loops
that were already inside `retrieve_chunks`, given names so the function stayed short and
readable after the new steps were added.

### Verified behaviour (real papers, real module)

| Question | Before | After (Attention) | After (BERT) |
|---|---|---|---|
| main topic | 0 | 3 passages | 3 passages |
| what is this paper about | 0 | 3 passages | 3 passages |
| research problem | 0 | 3 passages | 3 passages |
| methodology (+ train the model) | 0 | 3 passages | 3 passages |
| what do the authors conclude | 0 | 1 passage | 2 passages |
| key results | 1 | 3 passages | 3 passages |
| scaled dot-product attention | 4 | **4 (unchanged)** | 1 (unchanged) |
| BLEU score on English-to-German | 4 | **4 (unchanged)** | 1 (unchanged) |
| title of this paper | 1 | **1 (unchanged)** | 1 (unchanged) |
| bake sourdough bread | 0 | **0** | **0** |
| weather in Paris today | 0 | **0** | **0** |
| 2018 football world cup | 0 | **0** | **0** |
| fix my car engine | 0 | **0** | **0** |
| method for baking croissants | 0 | **0** | **0** |
| best recipe for pizza dough | 0 | **0** | **0** |

30 of 30 checks passed on both papers, and every returned page number was inside the real
document. The insufficient-evidence safeguard is untouched.

---

## 3. Bug 2 — page-specific questions failed with HTTP 502

### What was actually wrong

`check_no_prose_page_references()` in `backend/chat.py` removed the valid `[Page N]`
markers and then rejected the answer if **any** page number remained in the text. The
problem is that the natural answer to "what does page 6 describe?" begins
"Page 6 describes…", so a correct answer was always rejected.

Live evidence from the audit — all three providers were spent and the user got a 502:

```
gemini     → failed (rate_limit, 429)   phase=request
groq       → failed (invalid_output)    phase=validation
openrouter → failed (invalid_output)    phase=validation
POST /chat → 502 Bad Gateway
```

Both backups failed in the **validation** phase, not the request phase: the AI answered
correctly and PaperLense threw the answer away.

### What was changed

The rule was made precise instead of absolute. `check_prose_page_numbers_are_cited()`
replaces the old function:

> A page number in ordinary prose is allowed **only if the answer also cites that page**
> with a `[Page N]` marker.

That is safe because the bracketed markers are themselves checked against the passages we
actually retrieved (step 5 of `parse_grounded_answer`). So a prose page number that
matches a real citation is transitively verified; one that does not is refused.

Two supporting changes:

- `PROSE_PAGE_REFERENCE` became `PROSE_PAGE_NUMBER`, with a capture group so the number
  can be compared against the citations.
- The steps in `parse_grounded_answer` were reordered: citations are collected (step 2)
  before the prose check (step 3), because the prose check now needs to know what was
  cited.

A bracketed reference spelled any other way — `[page 6]`, `[Pages 6]`, `[Page 06]` — is
**still always rejected**. Those imitate the citation format without matching it, so they
would bypass the citation checks entirely.

### The frontend had to change too

`frontend/src/ChatPanel.jsx` runs the same validation independently, so the backend fix
alone would not have been enough — the browser would have rejected answers the server had
already approved, and the user would still have seen an error.

`usesOnlyBracketedPageReferences()` became `prosePageNumbersAreCited()`, applying exactly
the same rule, and `isValidAnswer()` now computes the citations before calling it. The
comment in that file states explicitly that this check must never be stricter than the
backend's.

### Protections deliberately kept

| Protection | Still enforced by |
|---|---|
| Only actual retrieved pages can be cited | `check_citations_match_sources` |
| Invented page numbers rejected | `check_citations_match_sources` |
| Every non-empty paragraph needs a citation | `check_every_paragraph_is_cited` |
| Source IDs must belong to retrieved passages | `check_cited_ids_are_real` |
| A citation cannot refer to another document | passages come only from the current document's index |
| Alternate bracketed formats rejected | `check_prose_page_numbers_are_cited` |

---

## 4. Bug 3 — Groq HTTP 413 misclassified

### What was actually wrong

`provider_error_for_status()` in `backend/http_error_messages.py` had no branch for 413,
so it fell through to the catch-all: *"The AI provider rejected the configured model or
request"*, category `configuration`, HTTP 502. That wording points at a broken API key or
model name, when in fact nothing is misconfigured — the paper is simply larger than
Groq's free-tier request limit, and OpenRouter accepts the same paper.

### What was changed

**A new category, `payload_too_large`:**

```python
if status == 413:
    return ProviderError(
        "This paper is larger than that AI provider's request size limit.",
        413, category="payload_too_large", upstream_status=status,
    )
```

The same branch was added to `describe_api_failure()` in `backend/gemini_client.py`, so
all three providers classify a size rejection the same way rather than only the two that
share the OpenAI-style adapter.

**A clear final message.** `generate_with_failover()` in `backend/ai_providers.py` gained
one `if` block: when the last failure was `payload_too_large`, the combined error explains
the size limit instead of saying "please try again later", because retrying the same paper
cannot help:

> This paper is larger than the configured AI providers' request size limits. Try a
> shorter paper or a clearly labeled excerpt. Your PDF is still available and was not
> shortened.

**What was not changed:** the failover loop still tries each provider exactly once in
order, PaperLense still never shortens a paper, and the 120,000-byte summary input limit
was **not** reduced to fit Groq's smaller limit.

---

## 5. Why the new code stays simple

Every change is a plain function, a dictionary, or a tuple of phrases. There are no new
classes, no new dependencies, no regex tricks and no clever abstractions.

- The synonym bridge is a **dictionary literal** you can read top to bottom.
- `asks_for_paper_overview` is a **`for` loop over a tuple of phrases** returning
  `True`/`False` — deliberately not a large regex.
- `question_names_something_absent` is a **`for` loop with two `continue`s** and an
  explicit `return True`.
- The fallback is an **`if` on an empty list**, then a second `for` loop with one
  comparison.
- Bug 2's fix is a **`for` loop over the prose page numbers** with one `in` check.
- Bug 3's fix is **one `if` branch** in a function that was already a list of `if`
  branches.

`retrieve_chunks` grew two new steps but got **shorter to read**, because its two inner
loops moved into `find_matching_chunks` and `select_best_chunks`. Its docstring now lists
the four steps in order. Every new function has a short docstring stating its purpose,
input and output, and every threshold has a comment explaining the measured number behind
it (for example, the 0.0935 score that motivated the 0.05 floor).

---

## 6. New regression tests

**45 new backend tests and 12 new frontend tests. No existing test was edited, weakened
or removed** — the only non-addition anywhere in the test files is one import line that was
expanded to include the new function names.

### Bug 1 — `backend/tests/test_retrieval.py` (19 → 43)

A realistic five-page paper fixture (`RESEARCH_PAPER`) with abstract, introduction,
related work, method, results and conclusion sections. A realistic length matters: the old
failures only appear once common words like "method" lose their rarity value.

- 7 broad questions must now retrieve passages, within the four-passage limit, with page
  numbers inside the document.
- 3 specific questions must still rank the correct page first.
- 6 unrelated questions must still retrieve nothing (including "method for baking
  croissants", which shares a general word with the paper).
- The relaxed attempt must never exceed its passage limit.
- Unit tests for `question_names_something_absent`, `add_related_words` (including that it
  does not modify the caller's Counter), and `asks_for_paper_overview`.

### Bug 2 — `backend/tests/test_chat.py` (66 → 80)

- 5 valid phrasings accepted: `Page 2 describes…`, `on page 2`, `as reported on page 2`,
  `p. 2`, `pp. 2` — each with the matching citation, each returning HTTP 200 with the
  wording unchanged and a real source page.
- Prose naming two cited pages accepted (`Pages 2 and 3 … [Page 2] [Page 3]`).
- 7 invalid cases still rejected with HTTP 502: prose with no citation; prose naming
  page 99 while citing page 2 (three variants); `[Page 99]` that was never retrieved; a
  paragraph with no citation; a source ID that does not exist.
- Direct unit tests of `check_prose_page_numbers_are_cited`, including that `[page 6]`
  is still refused.

### Bug 2 — `frontend/src/ChatPanel.test.jsx` (73 → 85)

The same valid and invalid cases driven through the real component, confirming the browser
accepts what the backend accepts and still rejects what it should.

### Bug 3 — `backend/tests/test_failover.py` (19 → 26)

- 413 classified as `payload_too_large` with status 413, and its message mentions size
  rather than credentials or model configuration.
- A guard that 400 and 404 remain `configuration` while 413 does not, so 413 cannot
  silently fall back into the catch-all branch again.
- Groq 413 → OpenRouter success, with Groq attempted exactly once.
- Gemini failure → Groq 413 → OpenRouter success, asserting provider order and exactly
  three calls (no retries).
- The 413 is logged as `category=payload_too_large upstream_code=413` without leaking the
  provider's response body or the API key.
- All three providers returning 413 → HTTP 413 with the size-limit explanation, each
  provider tried once, the upload still available, no summary cached.
- A 413 is not remembered as permanent: a later summary still succeeds.

---

## 7. Test results

| Suite | Before | After | Change |
|---|---|---|---|
| **Backend total** | 196 passed | **241 passed**, 0 failed | **+45** |
| — `test_retrieval.py` | 19 | **43** | +24 |
| — `test_chat.py` | 66 | **80** | +14 |
| — `test_failover.py` | 19 | **26** | +7 |
| — `test_api.py` | 27 | 27 | — |
| — `test_pdf_processing.py` | 15 | 15 | — |
| — `test_summarization.py` | 50 | 50 | — |
| **Frontend total** | 73 passed | **85 passed**, 0 failed | **+12** |
| **Production build** | passed | **passed** (23 modules, 117 ms) | — |
| CSS bundle | 17.25 kB | 17.25 kB, identical hash | unchanged |

One pre-existing warning remains (Starlette `TestClient` httpx deprecation), unrelated to
this work.

### Live verification — all three bugs, real providers

Run against the real 15-page *Attention Is All You Need* paper. Three requests total, to
avoid unnecessary quota use.

**Bug 1** — *"What methodology did the authors use to train the model?"*
Previously: insufficient evidence, zero chunks, no provider call.

```
HTTP 200 | insufficient=False | sources: chunk-1 p1, chunk-24 p8, chunk-29 p10
"The authors trained the Transformer model on WMT 2014 English-to-German and
 English-to-French translation tasks... beam search with beam size 4 and length
 penalty alpha=0.6... [Page 1] [Page 8] [Page 10]"
```

**Bug 2** — *"What does page 6 describe about positional encoding?"*
Previously: HTTP 502 after all three providers failed validation.

```
HTTP 200 | insufficient=False | sources: chunk-16 p6
"Page 6 explains that because the model lacks recurrence and convolution, positional
 encodings are added to input embeddings... PE(pos,2i) = sin(pos/10000^(2i/dmodel))
 ... [Page 6]"
```

The answer opens with exactly the prose wording that used to cause the 502, and its
citation was validated against a real retrieved passage on page 6. The content is
factually correct.

**Bug 3** — the live summary of the same paper produced the real Groq rejection:

```
gemini     → failed  category=upstream          upstream_code=503
groq       → failed  category=payload_too_large  upstream_code=413   ← was "configuration"
openrouter → success
summary HTTP 200, all five sections
```

This is the fix working in production conditions: Groq's 413 is now named for what it is,
and failover continued to OpenRouter, which summarised the paper successfully.

**Live providers used:** Groq and OpenRouter. Gemini returned 503/timeouts during this
session and was not successfully exercised live; its code paths are covered by mocked
tests. No live result in this report is inferred from a mock, and no mocked result is
described as live.

---

## 8. Files modified

| File | Change |
|---|---|
| `backend/retrieval.py` | Bug 1: synonym map, overview phrases, generic-word set, absent-subject guard, fallback, two extracted helpers, reworked `retrieve_chunks`, updated module docstring |
| `backend/chat.py` | Bug 2: `check_prose_page_numbers_are_cited` replaces `check_no_prose_page_references`; `PROSE_PAGE_NUMBER` captures the number; step order and numbering updated |
| `frontend/src/ChatPanel.jsx` | Bug 2: `prosePageNumbersAreCited` replaces `usesOnlyBracketedPageReferences`; citations computed first |
| `backend/http_error_messages.py` | Bug 3: new 413 branch with category `payload_too_large`; docstring rule list updated |
| `backend/gemini_client.py` | Bug 3: matching 413 branch in `describe_api_failure` |
| `backend/ai_providers.py` | Bug 3: size-specific final message when every provider rejects on size |
| `backend/tests/test_retrieval.py` | +24 tests |
| `backend/tests/test_chat.py` | +14 tests |
| `backend/tests/test_failover.py` | +7 tests |
| `frontend/src/ChatPanel.test.jsx` | +12 tests |
| `docs/FINAL_BUGFIX_REPORT.md` | This report (new) |

**Not touched:** `.env`, `.env.example`, `.gitignore`, `requirements.txt`,
`package.json`, `package-lock.json`, `pytest.ini`, `App.css`, any other component, any
model name, and `docs/DEVELOPER_HANDOVER.md` / `docs/FINAL_AUDIT_REPORT.md` /
`docs/REFACTOR_REPORT.md`.

The readability refactor is fully preserved. Two test files had their line endings
normalised back to LF after an editing script converted them to CRLF, matching the
`eol=lf` rule in `.gitattributes`; no content was changed by that.

---

## 9. Remaining limitations

**Honest limits of the Bug 1 fix.** Retrieval still matches words, not meaning. The
synonym map covers the common research vocabulary — topic, problem, method, conclusion,
results, contribution, limitation — but a question phrased with a synonym outside that map
can still miss. Proper semantic search needs sentence embeddings, which would add a large
dependency, and that trade-off was deliberately not taken.

**The overview shortcut returns the paper's opening**, not a targeted passage. For a
paper whose abstract is unusually sparse, "what is the main topic?" may retrieve less
useful evidence than the ideal. The AI's insufficient-evidence path still covers that case
honestly.

**The fallback can surface weaker evidence.** When the normal search finds nothing, up to
three lower-scoring passages are sent instead. They always passed the word checks, and the
AI is still required to decline when they do not support an answer, but an answer built
from fallback evidence is less certain than one from a confident match. This is the
intended trade: an honest attempt with cited evidence, rather than a blanket "not enough
evidence".

**Bug 2's rule allows a page number in prose only when cited.** It does not catch every
conceivable phrasing — "the following page" or "two pages later" are prose with no digit
and are not checked, because they are not page references a reader could mistake for a
citation. The security property that matters is unchanged: no page number that was not
retrieved can ever appear as a citation.

**Groq still cannot summarise full-length papers.** Bug 3 fixed the *classification*, not
the limit. Groq's free-tier request size remains smaller than a 15-page paper, so it stays
a summary backup in name only while remaining fully usable for Q&A, where only four
passages are sent. Fixing that properly would mean either a paid tier or chunked
summarisation, both outside this task.

**Gemini's free-tier quota is still 20 requests per day,** and Gemini was unavailable
throughout this session. That is an account limit, not a defect, and the failover design
is why the application kept working.

---

## 10. Git status

```
Branch:       codex/multi-provider-failover
HEAD:         9fe8bc8  (unchanged — nothing was committed)
Working tree: 16 modified, 12 untracked
```

**Modified (16):** `README.md`, `backend/ai_errors.py`, `backend/ai_providers.py`,
`backend/chat.py`, `backend/gemini_client.py`, `backend/main.py`,
`backend/pdf_processing.py`, `backend/retrieval.py`, `backend/summarization.py`,
`backend/tests/test_chat.py`, `backend/tests/test_failover.py`,
`backend/tests/test_retrieval.py`, `frontend/src/App.css`, `frontend/src/App.jsx`,
`frontend/src/ChatPanel.jsx`, `frontend/src/ChatPanel.test.jsx`.

**Untracked (12):** `backend/http_error_messages.py`,
`backend/openai_compatible_client.py`, `frontend/src/DocumentPreview.jsx`,
`frontend/src/Icon.jsx`, `frontend/src/PageSections.jsx`, `frontend/src/SummaryCard.jsx`,
`frontend/src/UploadCard.jsx`, `frontend/src/fileSize.js`,
`docs/DEVELOPER_HANDOVER.md`, `docs/FINAL_AUDIT_REPORT.md`, `docs/REFACTOR_REPORT.md`,
`package-lock.json` (the pre-existing stray empty file at the repository root), plus
`docs/FINAL_BUGFIX_REPORT.md` from this session.

No commit, push, merge, reset, stash or deploy was performed. No temporary file, local
PDF, secret or diagnostic log was added to the repository; all test papers and scripts
stayed in a scratch directory outside the project.
