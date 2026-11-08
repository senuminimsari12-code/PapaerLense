# PaperLense — Beginner-Readability Refactor Report

**Date:** 2026-11-08
**Branch:** `codex/multi-provider-failover`
**Baseline commit:** `9fe8bc8`
**Goal:** make the existing codebase readable for a beginner without changing what it does.

**Nothing was committed.** No feature was added or removed. No test was weakened, skipped or edited.
`.env`, `.gitignore`, `requirements.txt`, `package.json`, `package-lock.json` and `pytest.ini` are untouched.

---

## A. Refactoring summary

Five kinds of change were made, and nothing else.

**1. Dense expressions became named steps.**
The worst offenders were single statements doing three or four things at once. Each is now a short
function whose name says what it checks. `parse_grounded_answer` in `chat.py` went from one `try` block
containing eight inline checks to five named steps you can read in order. `validAnswer` in
`ChatPanel.jsx` went from one 60-line boolean expression to six small functions.

**2. The 750-line App component was split along real boundaries.**
`App.jsx` held all the state, both network requests, and the markup for the entire page. The markup now
lives in five focused components, so `App.jsx` contains only the behaviour. Its executable code dropped
from **725 lines to 249**.

**3. The provider system was reorganised so each file has one job.**
`ai_providers.py` previously mixed three concerns: the failover loop, the Groq/OpenRouter HTTP calls,
and the HTTP-status-to-message mapping. Gemini already had its own adapter file, so the backup providers
now have one too. `ai_providers.py` is now only the failover loop — the file you open to answer "how does
fallback work?".

**4. Every file and important function gained an explanation.**
Comments went from **58 to 863 lines** across the eight backend files. They explain *why* code exists,
not what the next line says: why `timeout=None` is correct, why `max(start + 1, ...)` prevents an
infinite loop, why clearing a file input lets you re-pick the same file, why middleware wraps `receive`.

**5. Names were made literal.**
`counts` → `question_words`, `ranked` → `scored_chunks`, `available` → `passages_by_id`,
`requestRunning` → `uploadInProgress`, `document` (state) → `uploadedDocument` so it no longer shadows
the browser's global `document`.

**Line counts went up, and that is intentional.** The brief was explicitly that fewer lines is not the
definition of simpler. Backend executable code grew by 150 lines because dense one-liners became named
steps; comments grew by 805 lines. The one place code shrank dramatically is `App.jsx`, because 476
lines of markup moved into components that each do one thing.

---

## B. Files changed

### Backend

#### `backend/main.py` — the web API (253 code lines, was 195)
*What it does:* defines the four endpoints and the two pieces of middleware, and holds the single
in-memory document.

*What was hard before:* the two ASGI middleware classes had one-line docstrings and no explanation of
the ASGI protocol, which is a large jump for anyone who has only seen normal FastAPI routes. Each
endpoint was one long function with the steps unlabelled. The response was built with a dict
comprehension over Pydantic internals. The repeated stale-document check appeared four times with no
shared explanation.

*What changed:*
- Both middleware classes now explain what ASGI's `scope`, `receive` and `send` are, and *why* this
  protection cannot be a normal FastAPI exception handler (it would buffer the upload and defeat the
  streaming limit).
- Each endpoint docstring lists its steps, and numbered comments mark them in the body.
- Extracted `get_current_document`, `raise_if_document_was_replaced` and
  `strip_directories_from_filename`, so the stale-request protection is explained once, in one place.
- `UploadResponse(**{key: document[key] for key in UploadResponse.model_fields})` became five explicit
  keyword arguments.
- Added a comment explaining that `add_middleware` order reads backwards.

*Why it is easier:* you can now read `upload_pdf` as five labelled steps, and the comment on
`documents` tells you immediately that the app holds exactly one document and why an old ID stops working.

#### `backend/ai_providers.py` — the failover loop (138 code lines, was 152)
*What it does:* tries Gemini, then Groq, then OpenRouter, and keeps the first valid answer.

*What was hard before:* this file was the hardest in the project. It used `TypeVar("Result")` with
`Callable[[str], Result]` generics; it packed the model-safety check into one expression with a nested
generator over three-element tuple unpacking; it carried the Groq/OpenRouter HTTP code and the status
mapping as well; and the loop used a `try/except/else` with a mutating `phase` variable.

*What changed:*
- The HTTP code moved to `openai_compatible_client.py`; the status mapping moved to
  `http_error_messages.py`. This file is now only the failover decision.
- The `TypeVar` generics were replaced with a plain signature plus a docstring explaining what
  `validate` is and, importantly, that the *same* validator runs for every provider.
- `(provider, key, model)` tuples became a `ConfiguredProvider` NamedTuple, so the code reads
  `provider.api_key` instead of `secret` from an unpacked tuple.
- The model-safety expression became `model_name_is_safe()`, with a comment explaining the real reason
  it exists: a key pasted into `GROQ_MODEL` would otherwise be written to the log.
- The time-budget division has a worked example in a comment (`90s / 3 providers = 30s each`).
- The file docstring is now a five-question summary of the entire provider system.

*Why it is easier:* "how does fallback work" is answerable by reading one 138-line file whose docstring
lists the five questions it answers.

#### `backend/chat.py` — grounded answers and citation checks (171 code lines, was 132)
*What was hard before:* `parse_grounded_answer` was one `try` block performing eight different checks
inline, with regexes written in place. Reading it, you could not tell which rule was being enforced or
why any of them mattered.

*What changed:* the checks became five named steps — `check_cited_ids_are_real`,
`check_no_prose_page_references`, `check_citations_match_sources`, `check_every_paragraph_is_cited`,
`build_source_passages` — each with a docstring saying what would go wrong without it. The regexes
became named module constants (`PAGE_CITATION`, `PROSE_PAGE_REFERENCE`, `PARAGRAPH_BREAK`). The
schema-building and the worked citation example moved into `build_answer_schema` and
`build_citation_example`. `generate_answer`'s inline `lambda` became a named nested `validate` function.

*Why it is easier:* the file docstring now states the single most important idea in the project —
*we do not trust the AI's citations, we re-check them* — and each check explains the specific failure it
prevents. Code grew by 39 lines because eight hidden rules became eight visible, documented ones.

#### `backend/retrieval.py` — chunking and TF-IDF search (153 code lines, was 123)
*What was hard before:* `chunk_pages` contained the whole boundary-finding algorithm inline — two
regexes, a list comprehension with a filter, `rfind`, and three branches deciding where the next chunk
starts — inside a `while` loop. The TF-IDF maths had no explanation.

*What changed:* the loop body became two named functions, `find_chunk_end` and `find_next_chunk_start`,
so `chunk_pages` reads as "find where this chunk ends, save it, find where the next begins". Added
`similarity_score` for the cosine calculation. `normalized_weights` now explains both of its steps,
including *why* vectors are scaled to length 1 (otherwise long chunks always look more relevant).
Renamed `counts` → `question_words`, `ranked` → `scored_chunks`, `seen_text` → `already_selected_text`.

*Two comments worth highlighting*, because both document real traps:
- `scored_chunks.sort(key=lambda scored: scored[0], ...)` — the explicit key is **required**. Without
  it, two equal scores would make Python compare the chunk dictionaries and raise a `TypeError`.
- The file docstring states the honest limitation plainly: this matches words, not meaning, so a
  question using a word the paper never uses scores zero.

#### `backend/pdf_processing.py` — validation and extraction (75 code lines, was 62)
*What changed:* the four cheap pre-parse checks became `check_bytes_look_like_a_pdf`, the three
post-open checks became `check_document_is_usable`, and preview building became `build_preview`. Magic
values became named constants (`PDF_MAGIC_BYTES`, `PDF_END_MARKER`). Comments explain why the order
matters (a renamed video is rejected in microseconds without touching the parser), why blank pages are
deliberately kept (dropping them would shift every later page number and break citations), and why
`is_repaired` is a rejection rather than a warning.

#### `backend/summarization.py` — the five sections (50 code lines, was 68)
*What changed:* the schema dict comprehension became `build_summary_schema` with an explicit loop. The
`any(...)` generator checking for text became a named loop. Comments explain why the limit is measured
in bytes rather than characters, why the field order is not arbitrary (it is the display order), and
why the app refuses an over-long paper instead of truncating it. This is the one backend file whose code
got meaningfully shorter.

#### `backend/gemini_client.py` — the Gemini adapter (135 code lines, was 93)
*What changed:* the seven-branch error mapping moved into `describe_api_failure`; config building moved
into `build_generation_config`; the key check moved into `read_api_key`. The status allowlist became a
named constant with a comment explaining it exists because the status field is provider-controlled text.
`response_text` now documents its three strict rules, including why "thinking" parts are dropped.

#### `backend/ai_errors.py` — the shared error type (7 code lines, unchanged)
*What changed:* code untouched; all four fields are now documented, including the fact that
`SummaryError` and `GeminiError` are just this class under a local alias — which was genuinely
confusing when reading the other files.

#### `backend/openai_compatible_client.py` — NEW (83 code lines)
Extracted from `ai_providers.py`. Its docstring answers the obvious question: why do two providers share
one file? Because Groq and OpenRouter both copy OpenAI's chat-completions API. Split into
`build_request_payload`, `read_generated_text`, `strip_markdown_code_fence` and `request_completion`.
Comments explain the two genuinely different behaviours: Groq enforces a real JSON schema, while
OpenRouter is asked for JSON in words and therefore sometimes needs a code fence removed.

#### `backend/http_error_messages.py` — NEW (26 code lines)
Extracted from `ai_providers.py`. One function, `provider_error_for_status`, reading as a short list of
rules. It is a separate file for a concrete reason: `ai_providers` imports
`openai_compatible_client`, so keeping this mapping in `ai_providers` would have created a circular
import.

### Frontend

#### `frontend/src/App.jsx` — state and requests (249 code lines, was 725)
*What was hard before:* one component held eight state variables, four refs, both network requests, the
icon set, and the markup for the header, intro, upload card, preview, summary, feature list, steps and
footer. The summary guard was a single four-condition `if`. Both error handlers were near-identical
twelve-line `if/else` chains.

*What changed:*
- All markup moved to `UploadCard`, `DocumentPreview`, `SummaryCard`, `PageSections` and the existing
  `ChatPanel`. This file now composes them and owns the logic.
- The four-condition guard became four named booleans (`noDocument`, `documentIsNoLongerCurrent`,
  `alreadyGenerating`, `alreadyHaveThisSummary`).
- Response checking moved into `isCompleteUploadResult` and `isCompleteSummaryResult`, each explaining
  why a response from our own backend is still checked.
- The duplicated error handling became `describeRequestFailure`, which documents the three ways a fetch
  can fail (`AbortError`, `TypeError`, `SyntaxError`) once instead of twice.
- The file docstring explains the single most confusing thing for a React beginner here: **why there are
  both `useState` and `useRef`** — state is for what you display, refs are for what you must check
  inside an async function before the next render.
- `document` state renamed `uploadedDocument`, removing the shadowing of the browser global.
- Timeouts became named constants.

#### `frontend/src/ChatPanel.jsx` — questions and answers (364 code lines, was 331)
*What was hard before:* `validAnswer` was one function containing a seven-condition `if`, a loop with a
ten-condition `if` inside it, two inline regexes, a `.some()` with a nested predicate, and a four-part
boolean return. It was the least readable code in the project. The render body also inlined the entire
markup for a chat turn inside `.map()`.

*What changed:* `validAnswer` became `isValidAnswer`, built from `hasValidAnswerShape`,
`collectSourcePages`, `findPageCitations`, `usesOnlyBracketedPageReferences`, `everyParagraphIsCited`
and `citationsMatchSources`. Each documents the failure it prevents. One turn's markup became a
`ChatTurn` component. Regexes and limits became named constants.

*Note:* `collectSourcePages` returns a `Set` or `null` rather than a boolean, so the caller can tell
"invalid" from "valid but empty" — a distinction the original expression made implicitly.

#### `frontend/src/UploadCard.jsx`, `DocumentPreview.jsx`, `SummaryCard.jsx`, `PageSections.jsx`, `Icon.jsx`, `fileSize.js` — NEW (574 code lines total)
All extracted from `App.jsx`, with the markup unchanged. Each takes plain props and holds no state.
Three nested ternaries that chose the drop-zone wording became a plain `if/else` chain assigning a
variable. The drag handlers became named functions with comments explaining why `preventDefault` is
needed to accept a drop, and why `dragleave` needs a `contains` check (otherwise the highlight flickers
when the pointer moves over a child element).

`SUMMARY_SECTIONS` is exported from `SummaryCard.jsx` and imported by `App.jsx`, so the five sections
are defined exactly once and the validation can never drift from the rendering.

#### `frontend/src/App.css` — styles (1385 lines, was 1278)
*What was hard before:* 1278 lines with **zero comments** and no section markers. Finding the rules for
one panel meant scrolling and guessing.

*What changed:* **no rule, selector, property or value was altered.** Added a file header explaining the
six-part organisation, a documented design-token block explaining what each `--variable` is for, 18
section banners, and a guide to reading the responsive blocks from widest to narrowest.

*Proof nothing changed visually:* the production CSS bundle is byte-identical before and after — same
size (17.25 kB / 4.44 kB gzipped) and the same content hash, `index-CrL22ZaI.css`. Comments are stripped
at build time, so an identical hash means identical output.

*Audit result:* all 98 CSS classes are referenced by the JSX, so there was no unused CSS to remove.
There were no duplicate top-level selectors and no selector deeper than three real parts, so no
complexity to unwind. The apparent `.processing-message` duplicate is intentional and idiomatic:
shared base styles followed by a single colour override.

#### `README.md`
Updated the architecture tree for the six new files, and corrected the stale "169 backend tests" to 196.

---

## C. Architecture

```text
PaperLense/
├── backend/                    Python API. Start reading at main.py.
│   ├── main.py                 The four endpoints, middleware, document store.  ← READ FIRST
│   ├── pdf_processing.py       Validate a PDF and extract numbered page text.
│   ├── retrieval.py            Chunking and the TF-IDF search index (the "R" in RAG).
│   ├── summarization.py        The five sections, their prompt and validation.
│   ├── chat.py                 Grounded answers and the citation checks.
│   ├── ai_providers.py         Provider order, shared deadline, failover loop.
│   ├── gemini_client.py        Gemini adapter (primary provider).
│   ├── openai_compatible_client.py  Groq + OpenRouter adapter (shared API format).
│   ├── http_error_messages.py  HTTP status → safe user message.
│   ├── ai_errors.py            The shared ProviderError type.
│   ├── requirements.txt
│   └── tests/                  196 tests. All provider traffic is mocked.
├── frontend/
│   ├── src/
│   │   ├── App.jsx             State, both requests, page composition.  ← READ FIRST
│   │   ├── UploadCard.jsx      Drop zone and upload errors.
│   │   ├── DocumentPreview.jsx Page stats and extracted-text preview.
│   │   ├── SummaryCard.jsx     The five summary sections.
│   │   ├── ChatPanel.jsx       Question form, history, citation checks.
│   │   ├── PageSections.jsx    Header, intro, feature list, steps, footer (no logic).
│   │   ├── Icon.jsx            The shared SVG icon set.
│   │   ├── fileSize.js         Byte formatting.
│   │   ├── App.css             Design tokens, layout, responsive rules.
│   │   └── *.test.jsx          73 tests.
│   ├── index.html              The HTML shell and React mount point.
│   └── vite.config.js
├── docs/                       Reports and guides.
├── .env                        API keys. Never committed.
└── .env.example                Placeholders only.
```

**Why it is split this way.** The backend has one file per stage of the pipeline, matching the order a
request travels. The frontend separates *behaviour* (`App.jsx`, `ChatPanel.jsx`) from *presentation*
(the other five), so the two files with logic are the two you study and the rest you can skim.

---

## D. Functionality verification

| Feature | Result |
|---|---|
| PDF upload | **VERIFIED LIVE** — `attention.pdf` and `bert.pdf`, HTTP 201 |
| PDF extraction | **VERIFIED LIVE** — 15 pages / 44,609 chars / 4,000-char preview, identical to the pre-refactor baseline |
| Automatic summary | **AUTOMATED** — 5 frontend tests incl. Strict Mode single-trigger (no browser available this session) |
| Five-section summary | **VERIFIED LIVE** — all five fields returned, correct order, facts correct against the paper |
| Manual retry | **AUTOMATED** — 3 frontend tests incl. post-replacement targeting |
| Q&A | **VERIFIED LIVE** — 6 questions, correct answers |
| Retrieval | **VERIFIED LIVE** — identical chunk IDs and pages to baseline (chunk-10/p4, chunk-23/p8, chunk-1/p1, chunk-13/p5, chunk-25/p9) |
| Citations | **VERIFIED LIVE** — every cited page matched a retrieved passage |
| Gemini | **VERIFIED WITH MOCKS ONLY** — live attempts returned HTTP 429; the free-tier daily quota (20 requests/day) is exhausted. Key and model name are valid. |
| Groq fallback | **VERIFIED LIVE** — handled Q&A and small-document summaries |
| OpenRouter fallback | **VERIFIED LIVE** — handled the full 15-page summary and Q&A |
| Document replacement | **VERIFIED LIVE** — old ID → 404; no contamination (a Transformer question on the BERT paper correctly returned insufficient evidence) |
| Provider failover chain | **VERIFIED LIVE** — Gemini 429 → Groq → OpenRouter, in order, one attempt each |
| PDF validation (6 cases) | **VERIFIED LIVE** — empty 400, non-PDF 415, truncated 422, image-only 422, encrypted 422, oversize 413; all messages identical to baseline |
| Duplicate-request protection | **VERIFIED LIVE** — 3 concurrent questions → 1×200, 2×409 |
| Stale-response protection | **AUTOMATED** — covered by backend and frontend tests |
| Error handling | **VERIFIED LIVE** — same status codes and same user-facing messages as baseline |
| Mobile responsiveness | **VERIFIED BY BUILD ONLY** — CSS output byte-identical (same content hash), so no visual change is possible. Not re-checked in a browser. |

**Live verification used Groq and OpenRouter only**, roughly 15 real calls. Gemini was not exercised
live because its daily quota is spent; its behaviour is covered by mocked tests. No claim of live
Gemini verification is made.

---

## E. Test results

| | Baseline (`9fe8bc8`) | After refactor | Change |
|---|---|---|---|
| Backend tests | **196 passed**, 0 failed | **196 passed**, 0 failed | none |
| — `test_api.py` | 27 | 27 | none |
| — `test_chat.py` | 66 | 66 | none |
| — `test_failover.py` | 19 | 19 | none |
| — `test_pdf_processing.py` | 15 | 15 | none |
| — `test_retrieval.py` | 19 | 19 | none |
| — `test_summarization.py` | 50 | 50 | none |
| Frontend tests | **73 passed** (3 files) | **73 passed** (3 files) | none |
| Production build | ✅ 17 modules | ✅ 23 modules | +6 (the new components) |
| CSS bundle | 17.25 kB / 4.44 kB gz | 17.25 kB / 4.44 kB gz | **identical hash** |
| JS bundle | 244.53 kB / 75.90 kB gz | 246.15 kB / 76.39 kB gz | +1.62 kB (module wrappers) |
| Backend module imports | ok | ok (10 modules) | +2 new |
| Unused Python imports | 0 | 0 | none |
| Unused JS imports | 0 | 0 | none |
| Lint / static analysis | none configured | none configured | unchanged |

**No test file was edited.** The suites are unchanged from the baseline, which is what makes 196/196 and
73/73 meaningful: the same assertions pass against the rewritten code. Tests were re-run after each of
the six refactor stages, not only at the end.

One pre-existing warning remains (Starlette's `TestClient` httpx deprecation). It is unrelated to this
work and was present at baseline.

---

## F. Complexity removed — concrete examples

**1. The model-safety check** (`ai_providers.py`)

```python
# Before — one expression, nested generator, three-element tuple unpacking
model_is_safe = re.fullmatch(r"[a-zA-Z0-9._:/-]{1,200}", model) and not any(
    model == secret or (len(secret) >= 12 and secret in model) for _, secret, _ in configured
)

# After — a named function with an explained loop, called as:
model_is_safe = model_name_is_safe(provider.model, configured_providers)
```
The new version's docstring states the actual reason it exists: if someone put their API key in
`GROQ_MODEL` by mistake, logging the "model" would leak the key.

**2. Building the upload response** (`main.py`)

```python
# Before — iterates Pydantic internals to build a dict, then unpacks it
return UploadResponse(**{key: document[key] for key in UploadResponse.model_fields})

# After — you can see exactly which five fields the frontend receives
return UploadResponse(
    document_id=document["document_id"],
    filename=document["filename"],
    page_count=document["page_count"],
    character_count=document["character_count"],
    preview=document["preview"],
)
```

**3. The summary guard** (`App.jsx`)

```js
// Before — four unlabelled conditions in one if
if (!targetDocument || currentDocument.current !== targetDocument ||
    summaryRequest.current || summary?.document_id === targetDocument.document_id) return;

// After — each condition named, so you can see what each one prevents
const noDocument = !targetDocument;
const documentIsNoLongerCurrent = currentDocument.current !== targetDocument;
const alreadyGenerating = Boolean(summaryRequest.current);
const alreadyHaveThisSummary = summary?.document_id === targetDocument?.document_id;
if (noDocument || documentIsNoLongerCurrent || alreadyGenerating || alreadyHaveThisSummary) return;
```

**4. Answer validation** (`ChatPanel.jsx`) — one 60-line function containing a 7-condition `if`, a loop
with a 10-condition `if`, and a 4-part boolean return, became six named functions. The orchestrator now
reads as a sequence, and `collectSourcePages` returns `Set | null` so "invalid" and "valid but empty"
are no longer conflated.

**5. Chunk boundaries** (`retrieval.py`) — the `while` loop body held two regexes, a filtered list
comprehension, an `rfind` fallback and a three-branch next-start decision. It is now
`find_chunk_end()` + `find_next_chunk_start()`, so `chunk_pages` reads as "find where this chunk ends,
save it, find where the next begins".

**6. The summary schema** (`summarization.py`)

```python
# Before — a dict comprehension inside a larger literal
"properties": {name: {"type": "string"} for name in PaperSummary.model_fields},

# After — build_summary_schema() with an explicit loop, and a docstring explaining
# that building it from model_fields keeps the schema and the model from drifting apart.
```

**7. Drop-zone wording** (`UploadCard.jsx`) — four nested ternaries inside JSX became a plain
`if/else if/else` chain assigning `dropZoneHeading` and `dropZoneMessage` before the markup.

**8. Three concerns in one file** (`ai_providers.py`) — the failover loop, the Groq/OpenRouter HTTP
calls, and the status mapping were interleaved. They are now three files, each with one job.

---

## G. Remaining complicated code, and why it must stay

These were deliberately **not** simplified. Each is complex because the requirement is complex, and all
are now documented rather than reduced.

**1. The two ASGI middleware classes (`main.py`).** Raw ASGI is a real step up in difficulty, and the
obvious simplification — a normal FastAPI exception handler — would **break the security property**. A
handler runs after the request body is buffered, so a 2 GB upload would already have been written to
disk before the limit was checked. `UploadBodyLimit` must wrap `receive` to count bytes as they arrive,
and `ContainUnexpectedErrors` must wrap only `send` so uploads keep streaming. Mitigated with a
docstring explaining the three ASGI arguments and why a handler will not do.

**2. `generate_with_failover`'s control flow (`ai_providers.py`).** The `try/except/else` with
`asyncio.timeout` and the running time budget looks intricate, but every piece is load-bearing: the
`else` must run only on success, the budget division is what stops a stalled provider starving its
backups, and the `phase` variable is what makes the logs say whether a provider failed to answer or
answered badly. Any flattening loses one of those. Mitigated with a worked example in a comment.

**3. `find_chunk_end` / `find_next_chunk_start` (`retrieval.py`).** Irreducible text-processing detail.
Chunks must not split sentences, must overlap so a boundary-straddling sentence survives intact, must
never span a page (or citations break), and must always move forward (or the loop hangs). Mitigated by
naming the two steps and commenting each rule.

**4. `response_text`'s traversal (`gemini_client.py`).** The
`response.candidates[0].content.parts[*].thought` walk is dictated by the SDK's response shape, not by
our choice. The strictness is deliberate: silently accepting a truncated answer would surface later as
a confusing validation error.

**5. The TF-IDF maths (`normalized_weights`, `similarity_score`).** `(1 + log(count)) * idf`, then
scaling to unit length, is standard information retrieval. Simplifying the formula would change the
search results. Mitigated by explaining what each step achieves and why unit-length scaling matters.

**6. Citation validation existing twice** (`chat.py` and `ChatPanel.jsx`). This duplication is
intentional defence in depth, not an oversight: the server guarantees correctness, and the browser
independently refuses to display anything it cannot verify. Removing either half would weaken a
security property, so both remain, each with a comment saying the other exists.

**7. The `useRef` / `useState` split (`App.jsx`, `ChatPanel.jsx`).** Inherent to async React. State
updates are not visible until the next render, so "is a request already running?" and "is this response
still wanted?" must be refs. This is the main conceptual hurdle in the frontend and is explained at the
top of `App.jsx`.

---

## H. Important functions, in the order to learn them

**Backend**

| # | Function | File | Why it matters |
|---|---|---|---|
| 1 | `upload_pdf` | `main.py` | The entry point for everything. Read its five steps. |
| 2 | `extract_pdf` | `pdf_processing.py` | Six validation checks, then page-by-page extraction. |
| 3 | `check_bytes_look_like_a_pdf` | `pdf_processing.py` | Why cheap checks run before the parser. |
| 4 | `read_limited_file` | `main.py` | How an oversized upload is stopped mid-stream. |
| 5 | `get_current_document` | `main.py` | Why an old document ID returns 404. |
| 6 | `raise_if_document_was_replaced` | `main.py` | The stale-request protection, in one place. |
| 7 | `summarize_document` | `main.py` | Caching, the 409 guard, then the provider call. |
| 8 | `build_paper_text` | `summarization.py` | Why a too-long paper is refused, not truncated. |
| 9 | `generate_summary` | `summarization.py` | Where the five-section request is assembled. |
| 10 | `parse_summary_response` | `summarization.py` | How a reply missing a section is rejected. |
| 11 | `chat_with_document` | `main.py` | The eight-step Q&A flow. |
| 12 | `follow_up_context` | `chat.py` | How "what about it?" finds its topic. |
| 13 | `chunk_pages` | `retrieval.py` | Why chunks never span a page. |
| 14 | `build_index` | `retrieval.py` | What TF-IDF actually computes. |
| 15 | `retrieve_chunks` | `retrieval.py` | How passages are chosen, and when none are. |
| 16 | **`parse_grounded_answer`** | `chat.py` | **The most important function in the project.** Why the AI cannot invent a page number. |
| 17 | **`generate_with_failover`** | `ai_providers.py` | **The second most important.** The whole provider story. |
| 18 | `find_configured_providers` | `ai_providers.py` | How a missing key skips a provider. |
| 19 | `request_gemini` | `gemini_client.py` | One primary-provider request, no retries. |
| 20 | `request_completion` | `openai_compatible_client.py` | One backup-provider request. |

**Frontend**

| # | Function | File | Why it matters |
|---|---|---|---|
| 21 | `uploadFiles` | `App.jsx` | Everything that happens when you choose a PDF. |
| 22 | `generateSummary` | `App.jsx` | The automatic trigger and its four guards. |
| 23 | `sendQuestion` | `ChatPanel.jsx` | Asking a question, and the stale checks. |
| 24 | `isValidAnswer` | `ChatPanel.jsx` | Browser-side citation verification. |
| 25 | `describeRequestFailure` | `App.jsx` | The three ways a fetch can fail. |

**Suggested learning order:** 1–6 (upload and the document store) → 7–10 (summaries) → 11–15
(retrieval and Q&A) → 16 (citation validation) → 17–20 (providers and failover) → 21–25 (the frontend).
That follows the brief's requested priority, and each group is understandable without the next.

---

## I. Git status

```
Branch:        codex/multi-provider-failover
HEAD:          9fe8bc8  "Add Gemini, Groq, and OpenRouter failover"  (unchanged — nothing committed)
Working tree:  12 modified, 11 untracked
```

**Modified (12):** `README.md`, `backend/ai_errors.py`, `backend/ai_providers.py`, `backend/chat.py`,
`backend/gemini_client.py`, `backend/main.py`, `backend/pdf_processing.py`, `backend/retrieval.py`,
`backend/summarization.py`, `frontend/src/App.css`, `frontend/src/App.jsx`,
`frontend/src/ChatPanel.jsx`.

**New from this refactor (8):** `backend/openai_compatible_client.py`,
`backend/http_error_messages.py`, `frontend/src/UploadCard.jsx`, `frontend/src/DocumentPreview.jsx`,
`frontend/src/SummaryCard.jsx`, `frontend/src/PageSections.jsx`, `frontend/src/Icon.jsx`,
`frontend/src/fileSize.js`.

**Pre-existing untracked, not touched (3):** `docs/DEVELOPER_HANDOVER.md`,
`docs/FINAL_AUDIT_REPORT.md`, `package-lock.json` (the stray empty file at the repository root).

**Confirmed untouched:** `.env`, `.env.example`, `.gitignore`, `backend/requirements.txt`,
`frontend/package.json`, `frontend/package-lock.json`, `pytest.ini`, and **every test file**.
No commit, push, merge or deploy was performed.

---

## J. Final assessment

### Beginner-readable — for the backend and for `App.jsx`. Partially beginner-readable for `ChatPanel.jsx` and the CSS.

**What is now genuinely beginner-readable:**

- **Every backend file.** Each opens with a docstring saying what it does and in what order to read it.
  Every important function has a docstring with its inputs, outputs and the reason it exists. The two
  genuinely difficult areas — ASGI middleware and the failover loop — are explained rather than hidden.
- **The execution flow.** Both paths requested in the brief are now traceable: `upload_pdf`'s docstring
  lists five numbered steps that appear as numbered comments in its body, and `chat_with_document`'s
  lists eight. You can follow a PDF from upload to answer without guessing.
- **The provider system.** "How does fallback work?" is answered by one 138-line file whose docstring
  poses and answers the five questions involved.
- **`App.jsx`.** At 249 lines of code it is readable in one sitting, and the `useState` versus `useRef`
  distinction — the thing most likely to confuse a React beginner here — is explained up front.

**What remains harder, honestly:**

- **`ChatPanel.jsx` is still the largest frontend file (364 code lines).** Its validation is now six
  clear functions, but the component still does four things: manages the input, manages the turn list,
  makes the request, and validates the response. Splitting the request logic into a custom hook would
  shorten it, but the brief explicitly warned against unnecessary custom hooks, and a hook would make
  the flow harder to follow, not easier. It is left as one component on purpose.
- **`App.css` is navigable, not simple.** 1385 lines is a lot of CSS. It now has a documented token
  system and 18 section banners so you can find what you need, but understanding the whole visual design
  still means reading a lot. Since all 98 classes are used and there were no duplicate or deeply nested
  selectors, there was nothing to safely remove — only navigation to add.
- **Async behaviour needs React knowledge.** `AbortController`, the stale-response checks, and the
  cleanup in `useEffect` are explained in comments, but they will take a second reading. That complexity
  is required: removing it would reintroduce the stale-response bugs the guards exist to prevent.
- **The TF-IDF maths needs the concept, not just the code.** The comments explain what each step
  achieves; they cannot teach information retrieval from scratch.

**Honest summary.** You should now be able to open any backend file and explain its purpose, trace a PDF
from upload through extraction, summary and Q&A, and explain the provider fallback — which were the
stated goals. The two remaining rough edges are `ChatPanel.jsx`'s size and the sheer volume of CSS, and
in both cases the cost of further simplification would be either a lost safety property or an extra
abstraction that hurts more than it helps.

**One thing to be clear about:** this refactor changed how the code reads, not what it does. The two
defects recorded in `docs/FINAL_AUDIT_REPORT.md` are still present and were deliberately left alone:
generic questions still retrieve nothing because of the `MIN_SIMILARITY` threshold, and page-targeted
questions still fail because the prose-page-reference rule rejects valid answers. Both are now easier to
find and fix — `MIN_SIMILARITY` has a comment explaining the symptom, and
`check_no_prose_page_references` is its own named function — but neither was changed, because fixing
them is a behaviour change rather than a readability one.
