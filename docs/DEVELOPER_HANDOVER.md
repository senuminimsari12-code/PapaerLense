# PaperLense developer handover

Source baseline `9fe8bc8` on `codex/multi-provider-failover`. This guide follows the repository code. The final audit report records what was exercised live and with mocks.

## A. Project structure

```text
PaperLense/
├── backend/
│   ├── main.py              FastAPI routes, middleware, and active document
│   ├── pdf_processing.py    PDF validation and numbered text extraction
│   ├── retrieval.py         Page-aware chunks and lexical search
│   ├── summarization.py     Five summary fields and validation
│   ├── chat.py              Follow-up context, answer schema, and citations
│   ├── ai_providers.py      Provider order, time budgets, and backup adapters
│   ├── gemini_client.py      Gemini SDK request and response adapter
│   ├── ai_errors.py         Safe provider errors
│   ├── requirements.txt    Pinned Python packages
│   └── tests/               PDF, API, retrieval, summary, chat, and failover tests
├── frontend/
│   ├── index.html           HTML shell and React mount point
│   ├── src/
│   │   ├── main.jsx         React entry point
│   │   ├── App.jsx          Upload, preview, and summary state
│   │   ├── ChatPanel.jsx    Question form, turns, and source excerpts
│   │   ├── App.css          Shared styles, responsive layout, and focus states
│   │   └── *.test.jsx       Component and API interaction tests
│   ├── vite.config.js       React plugin, environment directory, and test setup
│   ├── package.json         Frontend scripts and dependencies
│   └── package-lock.json    Reproducible frontend dependency resolution
├── docs/                    Phase reports, screenshots, and handover
├── .env.example             Placeholder keys, model defaults, and API address
├── pytest.ini               Backend test discovery
└── README.md                Local setup and workflow documentation
```

Start with [main.py](../backend/main.py), [pdf_processing.py](../backend/pdf_processing.py), and [App.jsx](../frontend/src/App.jsx). Follow the upload to the returned document ID before reading provider code. For Q&A, read [retrieval.py](../backend/retrieval.py) and [chat.py](../backend/chat.py) together. Then compare [ai_providers.py](../backend/ai_providers.py) and [gemini_client.py](../backend/gemini_client.py). The local `.env` and temporary debug artifacts live outside tracked application source.

## B. Execution flow

1. **Start the backend.** Uvicorn imports `backend.main:app`. `main.py` loads the root `.env` through `python-dotenv` with `override=False`, creates the FastAPI app and its empty `documents` dictionary, and registers routes and middleware. The standard API address is `http://localhost:8000`. The health route is `GET /api/health`.
2. **Start the frontend.** Vite serves `frontend/index.html` on port 5173 in development. `src/main.jsx` mounts `App` under React Strict Mode and loads `App.css`. `App.jsx` reads the public `VITE_API_BASE_URL`, which defaults to `http://localhost:8000`. The backend allows browser origins `http://localhost:5173` and `http://localhost:4173`.
3. **Select or drop a PDF.** The file picker and `handleDrop` lead to `App.uploadFiles`. It clears the previous UI state, checks for one nonempty `.pdf` within 20 MiB, and uses `fetch` to send `FormData` with a single `file` field to `POST /api/upload`. Browser validation gives early feedback. The backend independently validates the upload.
4. **Receive the request.** `UploadBodyLimit.__call__` caps the streamed request at 20 MiB plus 64 KiB for multipart overhead. `upload_pdf` accepts one uploaded file and zero extra form fields, strips the path from the display filename, and awaits `read_limited_file`. The multipart context closes uploaded files at exit.
5. **Extract numbered text.** `upload_pdf` runs `extract_pdf` in a thread pool. The extractor checks the PDF header and end marker, opens the byte stream with PyMuPDF, checks password requirements and parser repairs, and calls `page.get_text("text", sort=True)`. It retains 1-based numbers for all pages, including blank pages. It caps extraction at 500 pages and two million characters and limits the preview to 4,000 characters.
6. **Store the active document.** After extraction succeeds, `upload_pdf` creates a UUID4, replaces the single entry in `documents`, and returns HTTP 201 with the ID, filename, page count, character count, and preview. The complete numbered text stays in backend memory. A failed upload leaves the previous backend entry intact, although the initiating browser has already cleared its old display.
7. **Trigger the summary.** `uploadFiles` validates the upload response, stores it in React state and `currentDocument`, and calls `generateSummary(result)` once from the successful upload handler. It starts the call without awaiting it, so preview and chat can be ready during generation. `generateSummary` posts to `/api/documents/{document_id}/summary`, and the backend `summarize_document` checks for the active ID, a cached result, or an in-progress request.
8. **Send the first provider attempt.** `generate_summary` calls `build_paper_text` to join all pages with their original numbers. The summary input cap is 120,000 UTF-8 bytes. `generate_summary` passes that text, its prompt, a five-field JSON schema, and its validator to `generate_with_failover`. If Gemini is configured, `request_gemini` sends the request through the async Google Gen AI SDK. `response_text` accepts one completed candidate, joins visible text parts, and excludes thinking parts.
9. **Handle a failed Gemini attempt.** The orchestrator logs the safe provider name, model, failure category, status code when available, phase, and elapsed time. It advances in order after configuration rejection, transport failure, timeouts, upstream errors, or output validation failure. Missing keys skip attempts. The 90-second request budget is shared, with each attempt receiving the remaining time divided by the number of configured attempts left.
10. **Try Groq.** `_request_completion` sends a backend Bearer-authenticated request to Groq's chat completions endpoint. It requests strict JSON Schema output and passes completed text back to the same local validator.
11. **Try OpenRouter if needed.** The same adapter sends a Bearer-authenticated request to OpenRouter with the fixed configured model. It appends JSON instructions to the system message, accepts completed text, and can strip one enclosing Markdown code fence. Local validation still decides whether the result is usable.
12. **Return the summary.** `parse_summary_response` validates the five required nonempty, bounded fields and rejects extra fields. The route checks that the document still owns the active slot, caches the validated result, and returns `SummaryResponse`. `App.generateSummary` checks the ID and payload, then renders the sections in a fixed order. A failure exposes a manual retry. An already cached result avoids provider calls.
13. **Submit a question.** `ChatPanel.sendQuestion` posts JSON containing `question` to `/api/documents/{document_id}/chat` and tracks an individual UI turn. `chat_with_document` validates the active document and determines whether a preceding question helps resolve a short follow-up. It checks the cache before retrieving and rejects overlapping chat requests for that document.
14. **Select relevant text.** The first uncached question builds the document index in a thread pool with `build_index`. `chunk_pages` creates page-local excerpts of up to 1,400 characters and uses a target overlap of 220 characters. `retrieve_chunks` selects up to four distinct chunks using lexical overlap and TF-IDF cosine scores. A recognized title question uses the first chunk. A single-term definition can retain exact matches below the general similarity threshold.
15. **Generate a grounded answer.** With zero matches, the API returns its standard insufficient-evidence answer immediately. Otherwise, `generate_answer` creates a JSON payload with the question, optional prior topic question, and retrieved chunks with original page numbers. The same evidence and validator are reused across provider attempts. A validated insufficient-evidence result also ends the attempt sequence.
16. **Validate and render citations.** `parse_grounded_answer` checks that all cited IDs are unique and belong to the retrieved set, that the inline `[Page N]` values agree with the cited source pages, and that every nonempty paragraph has a page marker. It builds returned excerpts from the original chunks. `ChatPanel.validAnswer` checks the document ID, page bounds, and payload consistency before `ChatPanel` renders plain text with expandable source excerpts.
17. **Replace the PDF.** The browser clears old preview and summary state, aborts the old summary request, and remounts `ChatPanel` using the new ID or the empty-state key. Unmount cleanup aborts chat. The backend keeps the old entry until new extraction succeeds, then replaces it. Identity checks after asynchronous work reject a late result for an evicted document. Client-side abort and server-side identity checks protect the view even if an upstream request has already started.

## C. Twenty functions to trace

| # | Function and location | Purpose | Input → output | Called by → calls next |
|---|---|---|---|---|
| 1 | `App.uploadFiles` · [App.jsx](../frontend/src/App.jsx) | Validate file selection and register the accepted upload | File list → preview state or an upload error | Picker or `handleDrop` → `fetch`, `generateSummary` |
| 2 | `UploadBodyLimit.__call__` · [main.py](../backend/main.py) | Count streamed upload bytes before the multipart parser consumes them | ASGI scope, receive, send → delegated request or HTTP 413 | ASGI middleware stack → wrapped app and bounded receive |
| 3 | `upload_pdf` · [main.py](../backend/main.py) | Parse multipart data and register successful extraction | FastAPI request → `UploadResponse` or HTTP error | `POST /api/upload` → `read_limited_file`, `extract_pdf`, `uuid4` |
| 4 | `read_limited_file` · [main.py](../backend/main.py) | Read bounded byte chunks from the uploaded file | Starlette `UploadFile` → bytes or HTTP 413 | `upload_pdf` → `UploadFile.read` |
| 5 | `extract_pdf` · [pdf_processing.py](../backend/pdf_processing.py) | Validate PDF structure and extract page text | PDF bytes → page and character counts, numbered text, preview | `upload_pdf` in a thread pool → `pymupdf.open`, `page.get_text` |
| 6 | `App.generateSummary` · [App.jsx](../frontend/src/App.jsx) | Request a summary and keep stale results out of the UI | Current document response → summary state or retryable error | Successful `uploadFiles` or manual button → `fetch`, response checks |
| 7 | `summarize_document` · [main.py](../backend/main.py) | Apply document, cache, and in-flight checks | Document ID → `SummaryResponse` or HTTP error | Summary route → `generate_summary` |
| 8 | `generate_summary` · [summarization.py](../backend/summarization.py) | Build the prompt, input and schema for the summary | Numbered pages → validated `PaperSummary` and model ID | `summarize_document` → `build_paper_text`, `generate_with_failover` |
| 9 | `parse_summary_response` · [summarization.py](../backend/summarization.py) | Enforce the five-field output contract | JSON text → `PaperSummary` or safe error | Orchestrator validator callback → Pydantic `model_validate_json` |
| 10 | `generate_with_failover` · [ai_providers.py](../backend/ai_providers.py) | Try configured providers within a shared deadline | Request type, prompt, schema, validator, budgets → validated result and model | `generate_summary` and `generate_answer` → provider adapters, validator |
| 11 | `request_gemini` · [gemini_client.py](../backend/gemini_client.py) | Translate a generation request into SDK options and classify SDK failures | Prompt, schema, token and time budgets → SDK response and model | Orchestrator → async Gemini `generate_content` |
| 12 | `_request_completion` · [ai_providers.py](../backend/ai_providers.py) | Build Groq or OpenRouter requests and unpack their response envelopes | Backup provider, key, model, content, schema, token cap → completed text | Orchestrator → `httpx.AsyncClient.post`, `_http_error` if needed |
| 13 | `ChatPanel.sendQuestion` · [ChatPanel.jsx](../frontend/src/ChatPanel.jsx) | Submit one question and update its chat turn | Submit event or failed turn → answer, loading, or error state | Chat form or retry → `fetch`, `validAnswer` |
| 14 | `chat_with_document` · [main.py](../backend/main.py) | Coordinate chat cache, local retrieval, provider use, and isolation | Document ID and `ChatRequest` → `ChatResponse` or HTTP error | Chat route → `follow_up_context`, `build_index`, `retrieve_chunks`, `generate_answer`, `remember_answer` |
| 15 | `follow_up_context` · [chat.py](../backend/chat.py) | Select the previous question for likely referential follow-ups | New and previous questions → previous question or `None` | `chat_with_document` → whitespace normalization and regex checks |
| 16 | `chunk_pages` · [retrieval.py](../backend/retrieval.py) | Split text into overlapping chunks with stable page provenance | Numbered pages → chunk IDs, text, page numbers, offsets | `build_index` → text normalization and boundary searches |
| 17 | `build_index` · [retrieval.py](../backend/retrieval.py) | Prepare searchable chunk vectors | Numbered pages → chunks, term weights, and vectors | First uncached chat in a thread pool → `chunk_pages`, `tokenize`, `normalized_weights` |
| 18 | `retrieve_chunks` · [retrieval.py](../backend/retrieval.py) | Rank relevant evidence and keep the shortlist small | Index and query string → up to four source chunks | `chat_with_document` in a thread pool → `tokenize`, `normalized_weights`, score and deduplication checks |
| 19 | `generate_answer` · [chat.py](../backend/chat.py) | Serialize evidence and specify the answer contract | Question, retrieved passages, optional previous question → grounded answer, sources, model | `chat_with_document` → `generate_with_failover` with a passage-bound validator |
| 20 | `parse_grounded_answer` · [chat.py](../backend/chat.py) | Enforce the relationship between answer citations and trusted source chunks | JSON answer and retrieved passages → `GroundedAnswer` plus original `SourcePassage` values | Orchestrator validator callback → Pydantic validation and citation checks |

## D. What the technologies do here

| Technology | PaperLense role |
|---|---|
| React | Holds the selected PDF metadata, summary, and chat turns in component state. Renders loading, error, and success from that state. |
| Vite | Serves the development frontend, bundles the static production build, and supplies the browser-visible API address. |
| FastAPI | Receives upload, summary, chat, and health requests. Pydantic models define the structured request and response contracts. |
| PyMuPDF | Opens the in-memory byte stream and extracts selectable text page by page. |
| Text chunking | Keeps excerpts small and page-local, with overlap to preserve context across a chunk boundary. |
| Retrieval and RAG | Retrieves a small set of relevant chunks locally, then gives those chunks to the model for grounded generation. The implementation uses lexical scoring. |
| Gemini | First configured generation attempt. The Google Gen AI SDK sends the schema, prompt, and text. |
| Groq | First backup. Its OpenAI-compatible chat completions endpoint receives the same task and a strict JSON schema. |
| OpenRouter | Second backup. Its chat completions endpoint receives schema instructions in the prompt and the application parses the returned JSON. |
| Environment variables | Keep provider credentials and model selection on the backend. The public `VITE_API_BASE_URL` only tells the browser where to send API requests. |
| API endpoints | Give upload, summary, and Q&A separate lifecycles. Chat and summary can run independently against one document ID. |
| JSON responses | Carry typed metadata, summary fields, questions, source IDs, and page numbers. The PDF upload itself uses multipart form data. |
| Page citations | Allow a reader to check an answer against the PDF. The backend derives excerpt text and source page metadata from retrieval. |

## E. Twenty interview questions

1. **What is PaperLense's architecture?** React and Vite provide the browser UI. FastAPI accepts a PDF and stores extracted pages in memory. Summary and Q&A use the same ordered provider orchestrator, and Q&A has its own local retrieval stage.
2. **How do the two local services communicate?** The browser uses HTTP `fetch` with the configured API base URL. FastAPI allows the two explicit local Vite origins. A browser request can require a CORS preflight.
3. **Why does PDF upload use multipart form data?** The payload contains file bytes. The browser creates `FormData` with a field called `file`, and FastAPI uses Starlette to parse the multipart stream.
4. **What happens if a large upload omits `Content-Length`?** The middleware counts received bytes, and the file reader separately enforces the exact 20 MiB file limit while reading chunks.
5. **How does the backend decide whether a PDF can be processed?** It checks the header and end marker, opens with PyMuPDF, checks password requirements and repairs, enforces limits, and requires extractable text.
6. **What gets stored after a successful upload?** The global document slot keeps the UUID4, filename, preview, counts, and numbered page text. Cached summary, retrieval index, and chat state are added as needed.
7. **Why run PyMuPDF and retrieval in a thread pool?** These operations are synchronous. Moving them to a worker thread lets the asyncio event loop continue serving other I/O while that operation runs.
8. **What prevents automatic summary generation from firing twice?** It starts inside the accepted upload handler. Request refs block overlapping browser operations, and the backend rejects a duplicate in-flight summary or returns the completed cached result.
9. **What text goes to the summary model?** The whole extracted document with page labels, up to 120,000 UTF-8 bytes. A larger input is rejected before any summary provider call.
10. **How is a generated summary validated?** The common validator parses JSON with Pydantic and requires the five expected nonempty strings within their length bounds. The frontend also checks the document ID and returned section values.
11. **What does TF-IDF mean in this project?** The score favors repeated terms within a chunk and terms that are rarer across the document's chunks. PaperLense normalizes the vectors and compares them with a dot product, which yields cosine similarity.
12. **Why keep each chunk on one page?** A chunk keeps an unambiguous page number for citation. Adjacent chunks can overlap within a page to carry a sentence or term across a boundary.
13. **How does follow-up context work?** The backend uses lightweight pronoun and phrase rules to optionally include the previous topic question. The retrieved excerpts remain the source evidence, and the UI shows the context question when present.
14. **When can chat finish without contacting an AI provider?** An exact cached question-and-context match returns its cached response. An uncached question with zero relevant chunks returns the standard insufficient-evidence result locally.
15. **How does the citation validator catch invented pages?** It checks chunk IDs against the actual retrieved set, compares the inline citation page set with the trusted pages of those IDs, and requires a citation in each nonempty answer paragraph.
16. **What happens when Gemini is unavailable?** The orchestrator logs a classified failure and attempts Groq, followed by OpenRouter when needed and time permits. Every provider must pass the same task validator.
17. **How are failure latency and cost bounded?** A request has one 90-second backend budget and up to one attempt per configured provider. Time is reserved for later providers, and successful summary and chat responses can be reused from the cache.
18. **What keeps provider credentials away from the browser?** The Python process reads backend-only environment variables and uses them to authenticate outbound requests. Browser code sees the local API URL and application response data.
19. **How are uploaded instructions treated?** Provider prompts label documents, questions, and passages as untrusted evidence. Typed output and citation validation add checks. A valid citation still requires human judgment about whether the cited text supports the claim.
20. **What does the test suite prove about providers?** Backend integration tests run the real local API and parsing code with controlled provider transports. Frontend tests simulate API responses and check user-visible state. Live requests establish model and credential behavior for the tested inputs.

## F. Limitations to explain honestly

| Limitation | Why it exists and what it means | Possible future direction |
|---|---|---|
| Single active document per backend process | A global dictionary represents a one-person workspace. Another successful upload replaces it. Restarting or reloading the process clears it. Multiple independent users or workers would disagree about the active document. | Add authentication, ownership checks, and a shared durable store if the scope becomes multi-user. |
| Extractable text is required | PyMuPDF uses text extraction. Scanned pages, images, and plots have no OCR or vision pipeline. Multi-column layouts may extract in imperfect order. | Add a bounded OCR and layout-aware pipeline if those document types become a requirement. |
| Size and text limits differ | Upload, extracted text, summary bytes, and model token budgets constrain separate steps. A paper can upload successfully while its full-text summary exceeds a later limit. | Consider an explicit long-document summarization strategy with coverage checks. |
| Retrieval is lexical | The query must share enough relevant terms with a page chunk. Synonyms, misspellings, multi-hop questions, and evidence split across pages can lose recall. Up to four excerpts are sent. | Add evaluated hybrid search or reranking if the project later needs broader retrieval. |
| Follow-up detection is heuristic | Pronouns and a few phrases select a previous question. This can miss a reference or add context to an independent question. | Evaluate recorded follow-up cases and consider explicit context controls. |
| Citation validation is structural | The validator confirms that a real retrieved source exists and that page markers agree. It cannot decide whether every claim follows from the cited passage. Summary validation similarly checks structure. | Add source-by-source factual evaluation and show uncertain claims explicitly. |
| Provider availability and output vary | Three sequential services can fail from quotas, connectivity, deadlines, or malformed output. Failover reduces dependence on one service but adds possible wait time and may send the same request data to more than one provider. | Track measured failure rates and costs before changing provider budgets or policies. |
| CORS is a local browser rule | The API has no user authentication. CORS restricts browser origins, while a direct HTTP client can still call a reachable API. | Keep the prototype local. Add authentication and document authorization before wider access. |
| Browser abort is best-effort | Aborting an obsolete request prevents its result from appearing in the current UI. A remote request may already be underway. | Add end-to-end cancellation or cancellation-aware jobs if resource use becomes material. |
| External processing remains part of generation | The backend keeps extraction and retrieval local, then sends the full summary text or selected Q&A passages to whichever provider handles each attempt. | For sensitive documents, evaluate provider data policies or use an approved local model. |

## G. Learning order

1. **Python backend flow.** Open [main.py](../backend/main.py). Find app initialization, `documents`, and the three POST handlers. Describe the dictionary after one upload and after a second upload.
2. **PDF extraction.** Read [pdf_processing.py](../backend/pdf_processing.py) and its tests. Trace a three-page PDF with a blank middle page, then explain why page 3 stays page 3.
3. **API endpoints.** Walk through [test_api.py](../backend/tests/test_api.py). Match a multipart upload, summary request, and chat request to their route signatures and HTTP statuses.
4. **Retrieval and Q&A.** Read [retrieval.py](../backend/retrieval.py) and [chat.py](../backend/chat.py). Start with `chunk_pages` and follow a question to the validated excerpt returned by the API.
5. **Provider failover.** Read [ai_providers.py](../backend/ai_providers.py) and [gemini_client.py](../backend/gemini_client.py). Draw a three-row timeline and use [test_failover.py](../backend/tests/test_failover.py) to check your prediction about which provider runs next.
6. **React frontend flow.** In [App.jsx](../frontend/src/App.jsx), follow the accepted upload into `generateSummary`. In [ChatPanel.jsx](../frontend/src/ChatPanel.jsx), follow `sendQuestion` through request, response validation, and rendering. Explain why the document ID is also a React key.
7. **Error handling and testing.** Compare one rejected PDF, one duplicate request, one provider timeout, and one invalid citation. Identify the guard that catches each case, then locate its automated test. Practice explaining which test boundaries use mocks and what a live run adds.
