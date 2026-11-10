# PaperLense Phase 1 verification

Verified on 29 October 2026. Scope: upload, PDF validation/extraction, temporary document state and the initial UI. AI summaries, RAG, chat and OCR are not implemented.

## Files created

| File | Responsibility |
| --- | --- |
| `frontend/src/App.jsx` | File picker, drag and drop, upload/loading/error/success state, real text preview |
| `frontend/src/App.css` | Responsive layout, design tokens, focus and reduced-motion styles |
| `frontend/src/App.test.jsx` | Frontend request/state regression tests |
| `frontend/src/main.jsx`, `index.html`, `public/favicon.svg` | Browser entry point and local branding |
| `frontend/package.json`, `package-lock.json`, `vite.config.js` | Reproducible frontend dependencies, build and test commands |
| `backend/main.py` | Health/upload endpoints, multipart/request limits, CORS and single-document store |
| `backend/pdf_processing.py` | PDF validation, numbered page extraction and bounded preview |
| `backend/tests/` | Programmatically generated PDFs, processing and endpoint tests |
| `backend/requirements.txt`, `pytest.ini` | Pinned direct backend dependencies and test discovery |
| `README.md` | Windows/WSL setup, API contract, limitations and code explanations |
| `.gitignore`, `.gitattributes`, `.env.example` | Generated-file exclusions, line endings and optional public configuration |

## Features implemented

One PDF per request, 20 MiB file limit, independent content validation, damaged/password/image-only document errors, page-by-page text extraction, original page numbers, real metadata, a bounded preview and one in-memory document keyed by UUID. New selection clears previous browser results immediately. Loading locks repeated requests; errors support retry. Planned summaries/chat are labeled as planned.

## Actual verification results

Backend environment: Ubuntu WSL, Python 3.14.4, PyMuPDF 1.28.2, FastAPI 0.162.0. Frontend: Windows, Node 24.19.0, npm 11.17.0, React 19.3.1, Vite 8.3.5.

| Check / actual command | Result |
| --- | --- |
| `wsl --cd '/mnt/d/projects/PaperLense' --exec backend/.venv-wsl/bin/python3 -m pytest -q` | **37 passed**, no failures. One dependency deprecation warning: Starlette's httpx test-client adapter is deprecated; the current adapter works. |
| `npm test -- --reporter=dot` from `frontend/` | **14 passed**, no failures |
| `npm run build` from `frontend/` | Passed; production output generated in ignored `frontend/dist/` |
| `npm install` from `frontend/` | Completed; audit reported 0 vulnerabilities |
| `npm run dev` from `frontend/` | Vite started at `http://localhost:5173` |
| `wsl --cd '/mnt/d/projects/PaperLense' --exec backend/.venv-wsl/bin/python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` | Backend started successfully |
| `Invoke-RestMethod 'http://localhost:8000/api/health'` | `{"status":"ok"}` |
| Genuine paper uploaded through the browser picker, opened using Enter on the visible button | Passed; real document details and text appeared |
| Invalid replacement selected through the browser | Passed; useful non-PDF error and zero old text-preview elements |
| Retry after an invalid replacement | Passed; the genuine paper was processed successfully again |
| Browser views at 1280 px and 390 px | Layout visually inspected; desktop columns and mobile stacking are usable |

At the 390 px mobile viewport, the document width was 375 px (the remaining space was the scrollbar), with no horizontal overflow. Keyboard Tab navigation from the header reached the visible replacement button. Desktop and mobile screenshots are saved under `docs/screenshots/`.

The genuine research paper was [Attention Is All You Need, arXiv:1706.03762](https://arxiv.org/pdf/1706.03762). The downloaded copy produced **15 pages, 44,609 extracted characters and a 4,000-character preview**. Its full numbered page records were also checked directly using `extract_pdf`. The public paper was downloaded only to ignored `tmp/` for verification; it is not part of the published source.

Backend tests cover valid text, preserved blank-page numbering, renamed content, parser repair, truncation, image-only and blank PDFs, encryption, actual 20 MiB and exact-limit boundaries, page/character caps, streamed oversized requests, endpoint shapes, extra files/fields, memory replacement, path-safe filenames, CORS and generic unexpected failures. Frontend tests cover actual request shape, loading/duplicate submission guards, file/drop validation, server/network failures, malformed/incomplete responses, retry and stale-result removal.

Initial frontend failures came from whitespace-normalizing test queries and a non-unique page-count query; the queries were corrected to assert the actual rendered preview and page statistic. An initial exact-limit PDF fixture placed excessive padding between `startxref` and EOF, making it a damaged PDF; padding was moved after the trailer to keep the fixture valid. All tests above were rerun after these corrections.

## How to run on Windows

The complete first-time native Windows setup, optional environment configuration, WSL setup and troubleshooting are in [README.md](../README.md). On this machine the ready-to-use commands are:

Terminal 1:

```powershell
Set-Location 'D:\projects\PaperLense'
wsl.exe --cd '/mnt/d/projects/PaperLense' --exec backend/.venv-wsl/bin/python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```powershell
Set-Location 'D:\projects\PaperLense\frontend'
npm.cmd run dev
```

Open `http://localhost:5173`.

## Architecture explanation

React sends one file in `FormData`. FastAPI limits the request and file size, validates the multipart fields, and passes the bytes to PyMuPDF on a worker thread. Each page becomes a `{page_number, text}` entry. Successful extraction gets a random document ID and replaces the single backend memory record. Only metadata and the short preview return to React. The original PDF is not permanently saved.

## Interview preparation


## Remaining limits and unverified behavior

- **Native Windows backend execution is blocked by this machine's application-control policy.** PyMuPDF's native module failed to load. The same backend and tests were run successfully in Ubuntu WSL. Windows security settings were not changed. Native Windows startup is not claimed as verified.
- Browser drag-and-drop behavior is covered by automated frontend event tests; a physical operating-system drag into the browser was not manually performed.
- A full assistive-technology audit and testing on physical mobile devices were not performed. Keyboard picker activation and responsive browser widths were checked.
- Complex PDF reading order is best-effort. OCR, summaries, chat, retrieval endpoints, persistence, user isolation and public deployment are outside Phase 1.
- The project is a local single-user prototype. Run one backend process. Memory resets when it stops; uploads from different clients share that one process's memory slot.
