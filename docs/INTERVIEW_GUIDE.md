# Explaining PaperLense Phase 1

The main idea: React collects one file, FastAPI validates it, PyMuPDF extracts the page text, and React displays the real result. Page text stays in backend memory so a later phase can add retrieval and citations. Phase 1 does not make AI calls.

## 1. `uploadFiles(files)` — `frontend/src/App.jsx`

**Input:** a file list from the picker or drag-and-drop event. **Output:** no return value; it updates React state and sends a request.

It immediately removes the previous result, checks that exactly one non-empty PDF-named file is within the limit, and sends it as `FormData`. The browser supplies the multipart boundary. It checks the HTTP status and required response fields before displaying a successful result. It explains network/server errors and always unlocks the interface in `finally`.

Why it matters: a loading indicator is not proof that processing succeeded. Only a valid successful API response becomes document state. A ref guards against duplicate submissions immediately, while `isUploading` controls what the interface shows. The second ref points to the file input so a normal, keyboard-accessible button can open it. Clearing the input value permits selecting the same file again.

## 2. `handleDrop(event)` and `formatFileSize(bytes)` — `frontend/src/App.jsx`

`handleDrop` takes the browser's drop event, prevents the browser from opening the PDF, and passes the dropped files to the same upload function. It returns no value. Sharing the function keeps picker and drop validation consistent.

`formatFileSize` takes a byte count and returns a human-readable string such as `2.0 KB` or `1.5 MB`. It does not guess the page count or any document contents.

## 3. `UploadBodyLimit.__call__` — `backend/main.py`

**Input:** an HTTP request's stream, through the ASGI `scope`, `receive` and `send` interfaces. **Output:** forwards the request or raises HTTP 413.

This small middleware counts raw request bytes as they arrive. The whole upload request may contain at most 20 MiB plus 64 KiB of multipart overhead. This acts before form parsing, including for streamed requests with no `Content-Length` header. Without it, a file could already have been spooled by the multipart parser before the endpoint checks its size. CORS is placed outside this middleware so expected size-error responses can still be read by the frontend.

## 4. `read_limited_file(file)` — `backend/main.py`

**Input:** an `UploadFile`. **Output:** file bytes, or HTTP 413.

It reads in chunks of at most 64 KiB and stops as soon as it has one byte more than the 20 MiB file limit. It never relies on the browser's size check, MIME type or a claimed `Content-Length`. The request limit includes multipart metadata; this second check measures the PDF itself.

## 5. `extract_pdf(data)` and `PDFError` — `backend/pdf_processing.py`

**Input:** the PDF's bytes. **Output:** a dictionary with `page_count`, `character_count`, `pages` and `preview`.

It checks size, the `%PDF-` signature and a final EOF marker, then opens the bytes with PyMuPDF. A signature alone does not prove the PDF is readable. Password-protected, damaged or repaired documents are rejected. The document is opened in a `with` block so it is closed on both success and error.

An ordinary loop extracts each page using `get_text('text', sort=True)`. `enumerate(..., start=1)` preserves human page numbers. Blank pages remain in `pages` even though they contribute no characters. No text means an OCR explanation rather than a fake success. The function limits pages, extracted characters and preview length.

`PDFError` carries a safe message and an HTTP status code. Expected PDF failures can therefore be translated by the API without exposing parser internals. The extraction module can also be tested independently of HTTP.

## 6. `upload_pdf(request)` and the `documents` dictionary — `backend/main.py`

**Input:** one multipart request containing the `file` field. **Output:** HTTP 201 with the five documented response fields, or an error.

It rejects extra file/text fields and reads the file with a limit. `run_in_threadpool` keeps synchronous PDF parsing off the async event loop. On success, `uuid4()` creates a random document ID and the dictionary is cleared before the new record is inserted. That gives the local prototype a simple one-document retention rule. No `await` occurs between clearing and inserting.

The form's context manager closes temporary uploads. Raw bytes are released after processing. The response does not include every page's text; the backend retains the numbered pages for future retrieval. Failed replacement attempts leave the last good backend record intact, while React removes it from view when a new file is chosen. Those are separate, deliberate policies.

Tradeoff: one dictionary is simple and bounded, but it is shared by all users of the process and disappears after a restart. This is appropriate only for the local single-user prototype, with one server process. Future multi-user work needs separate ownership and persistent storage.

## 7. Error handling and exact CORS — `backend/main.py`

`health()` takes no input and returns `{'status': 'ok'}` so startup can be checked independently of PDFs.

Expected problems return 400/413/415/422 and a useful `detail`. `unexpected_error(request, error)` logs unexpected failures locally and returns a generic HTTP 500 message. File paths and exception text do not enter the client response.

CORS allows the exact documented origin, `http://localhost:5173`. A different hostname or port is a different origin. CORS is a browser access rule, not authentication; this phase is not a public multi-user deployment.

## 8. What the tests prove

Backend tests create real PDFs, including blank and encrypted documents, in memory. They check extraction and API behavior separately. Limits have boundary checks, including streamed uploads without `Content-Length`, and the single-document replacement policy is verified.

Frontend tests simulate HTTP results and verify what the user sees. They check stale content is cleared on new selection, client validation failure, server rejection and network failure. These tests do not prove a real backend connection; that is checked separately by uploading a genuine paper through the browser. Responsive layout and the keyboard picker also require browser checks, recorded in the verification report.
