"""The PaperLense web API. Start it from the repository root with:

    uvicorn backend.main:app

This file is the front door. Every request from the browser arrives here, and this is
the best place to start reading the project.

There are four endpoints:
  GET  /api/health                         - is the server alive?
  POST /api/upload                         - send a PDF, get a document_id back.
  POST /api/documents/{id}/summary         - generate the five-section summary.
  POST /api/documents/{id}/chat            - ask a question about the PDF.

The work itself lives in other files, so each endpoint here reads as a short list of
steps:
  backend/pdf_processing.py  - validate the PDF and pull out its text.
  backend/retrieval.py       - find the passages relevant to a question.
  backend/summarization.py   - build and check the five-section summary.
  backend/chat.py            - build and check a grounded answer with citations.
  backend/ai_providers.py    - call Gemini, then Groq, then OpenRouter.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse

from backend.ai_errors import ProviderError
from backend.chat import (
    ChatRequest, ChatResponse, INSUFFICIENT_ANSWER, build_evidence, chat_cache_key,
    follow_up_context, generate_answer, remember_answer,
)
from backend.document_sessions import (
    SESSION_HEADER, documents, get_current_document, prune_expired_documents,
    store_document, validate_upload_session,
)
from backend.pdf_processing import MAX_UPLOAD_BYTES, PDFError, extract_pdf
from backend.retrieval import PAGE_REFERENCE, build_index, retrieve_chunks
from backend.summarization import SummaryError, SummaryResponse, generate_summary

# Load API keys from the .env file at the repository root. override=False means a real
# environment variable always wins over the file, which is what you want in production.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="PaperLense",
    version="3.0.0",
    description="PDF extraction, structured summaries and grounded paper Q&A.",
)

# Extra room above the file limit for multipart form overhead (field names, boundary
# markers). Without it, a file at exactly the limit could be rejected for being a few
# hundred bytes too large once wrapped in a form.
MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024
MAX_CHAT_BODY_BYTES = 16 * 1024
MAX_ACTIVE_UPLOADS = 2
MAX_ACTIVE_AI_REQUESTS = 4

# How much we read from the network at a time while receiving an upload.
UPLOAD_READ_CHUNK_BYTES = 64 * 1024

# PyMuPDF must not run on multiple threads in the same process. A dedicated
# worker keeps PDF extraction off the event loop and handles one PDF at a time.
pdf_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf")


class UploadResponse(BaseModel):
    """What the frontend receives after a successful upload."""

    document_id: str
    session_id: str
    filename: str
    page_count: int
    character_count: int
    preview: str


class RequestBodyLimit:
    """Bound request bodies and concurrent PDF/AI work before reading the body.

    This is ASGI middleware, which is a lower level than a normal FastAPI route. It is
    worth the extra complexity for one reason: FastAPI only hands us the file after the
    multipart parser has already read the whole request and written big uploads to a
    temporary file. By then a 2 GB upload has already cost us 2 GB of disk.

    So this class sits in front of the parser and counts the bytes as they arrive. The
    moment the total goes over the limit, it raises, and the rest is never read.

    How ASGI works, in short: an application is a function taking three arguments.
      scope   - a dict describing the request (its type, path, headers).
      receive - an async function you call to get the next piece of the request body.
      send    - an async function you call to send part of the response.
    Middleware wraps one of those three and passes the rest through unchanged. Here we
    wrap `receive`, because the request body is what we want to measure.
    """

    def __init__(self, app):
        self.app = app
        self.active_requests = {"upload": 0, "AI": 0}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path == "/api/upload":
            group = "upload"
            active_limit = MAX_ACTIVE_UPLOADS
            busy_message = "Too many uploads are in progress. Please try again shortly."
            byte_limit = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_ALLOWANCE
            limit_message = "This upload exceeds the 20 MB (20 MiB) limit."
        elif path.startswith("/api/documents/") and path.endswith(("/chat", "/summary")):
            group = "AI"
            active_limit = MAX_ACTIVE_AI_REQUESTS
            busy_message = "Too many AI requests are in progress. Please try again shortly."
            # Leave room for a 1,000-character question even when JSON escapes it.
            byte_limit = MAX_CHAT_BODY_BYTES
            limit_message = f"The {path.rsplit('/', 1)[-1]} request exceeds the 16 KiB body limit."
        else:
            await self.app(scope, receive, send)
            return

        bytes_received = 0

        async def receive_and_count():
            """Stand in for `receive`, adding up the body size as it streams in."""
            nonlocal bytes_received
            message = await receive()
            bytes_received += len(message.get("body", b""))

            if bytes_received > byte_limit:
                raise HTTPException(413, limit_message)

            return message

        # Bound multipart buffers and old AI requests still winding down after replacement.
        if self.active_requests[group] >= active_limit:
            response = JSONResponse(
                {"detail": busy_message},
                status_code=503, headers={"Retry-After": "2"},
            )
            await response(scope, receive, send)
            return
        self.active_requests[group] += 1
        try:
            await self.app(scope, receive_and_count, send)
        finally:
            self.active_requests[group] -= 1


class ContainUnexpectedErrors:
    """Turn any unexpected crash into a plain 500, revealing nothing private.

    This middleware wraps `send` only, so it does not buffer the request body.

    The security point: a Python error message or traceback can easily contain an API
    key, a file path, or a sentence from the user's paper. So we log only the exception's
    TYPE (for example "KeyError") and send the user a fixed, generic sentence.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_and_remember(message):
            """Stand in for `send`, noting whether the response has begun."""
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_and_remember)
        except Exception as error:
            # Deliberately logs the type only, never str(error).
            logger.error("Unexpected server failure (%s).", type(error).__name__)

            if response_started:
                # Headers are already on the wire, so we cannot send a second response.
                # Raise a message with nothing private in it and let the server close
                # the connection.
                raise RuntimeError("The response could not be completed.") from None

            error_response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Something went wrong while processing this request. "
                              "Please try again."
                },
            )
            await error_response(scope, receive, send)


# Middleware order matters, and reads backwards: the LAST one added is the OUTERMOST,
# so it sees the request first. The effective order for an upload is therefore:
#   CORS  ->  RequestBodyLimit  ->  ContainUnexpectedErrors  ->  the endpoint.
def allowed_frontend_origins() -> list[str]:
    origins = ["http://localhost:5173", "http://localhost:4173"]
    for value in os.getenv("PAPERLENS_ALLOWED_ORIGINS", "").split(","):
        origin = value.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or "*" in origin or origin != f"https://{parsed.netloc}"):
            raise ValueError("PAPERLENS_ALLOWED_ORIGINS must contain exact HTTPS origins.")
        origins.append(origin)
    return origins


app.add_middleware(ContainUnexpectedErrors)
app.add_middleware(RequestBodyLimit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_frontend_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", SESSION_HEADER],
)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError):
    """Return a safe validation error without reflecting submitted data."""
    return JSONResponse(
        status_code=422,
        content={"detail": "Send a JSON object with one non-blank question of up to 1,000 characters."},
    )


@app.get("/api/health")
def health():
    """Report that the server is running. Used to check the backend is reachable."""
    return {"status": "ok"}


async def read_limited_file(file: UploadFile) -> bytes:
    """Read an uploaded file into memory, stopping just past the size limit.

    We read one chunk at a time and stop as soon as we are over the limit, so a huge
    file never fully loads. The "+ 1" in the size calculation is what lets us notice a
    file that is exactly one byte too big instead of silently accepting it.

    Raises HTTPException(413) if the file is too large.
    """
    data = bytearray()

    while True:
        bytes_still_allowed = MAX_UPLOAD_BYTES + 1 - len(data)
        chunk = await file.read(min(UPLOAD_READ_CHUNK_BYTES, bytes_still_allowed))

        # An empty chunk means the file has been read completely.
        if not chunk:
            break

        data.extend(chunk)

        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "This file exceeds the 20 MB (20 MiB) upload limit.")

    return bytes(data)


def strip_directories_from_filename(filename: str | None) -> str:
    """Keep only the file's own name, discarding any folder path the browser sent.

    Some browsers send "C:\\Users\\me\\paper.pdf". We keep just "paper.pdf" so the name
    cannot describe a location on disk. PaperLense never uses this name to open a file,
    but it is displayed back to the user, so it is cleaned anyway.
    """
    if not filename:
        return "document.pdf"

    # Treat Windows "\" and POSIX "/" the same, then take the final piece.
    return filename.replace("\\", "/").split("/")[-1]


@app.post(
    "/api/upload",
    response_model=UploadResponse,
    status_code=201,
    # Describes the multipart upload in the generated API docs at /docs. It is written
    # by hand because this endpoint reads the form itself rather than declaring a
    # File() parameter, so FastAPI cannot work out the shape on its own.
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {
        "schema": {"type": "object", "required": ["file"], "properties": {
            "file": {"type": "string", "format": "binary"}
        }}
    }}}},
)
async def upload_pdf(request: Request, response: Response):
    """Accept one PDF, extract its text, and register it as the current document.

    The steps, in order:
      1. Check the request really is a file upload.
      2. Take exactly one file out of the form.
      3. Read it, refusing anything over the size limit.
      4. Extract the text (this is where an invalid PDF is rejected).
      5. Replace any previous document and store this one under a new ID.
    """
    session_id = request.headers.get(SESSION_HEADER)
    validate_upload_session(session_id)
    # Step 1: reject anything that is not a file upload, such as a JSON body.
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "multipart/form-data":
        raise HTTPException(415, "Send one PDF as multipart/form-data using the 'file' field.")

    # Using `async with` on the form matters: when the block ends, Starlette closes the
    # upload and deletes any temporary file it created, including when an error is
    # raised. That is how PaperLense avoids leaving PDFs behind on disk.
    async with request.form(max_files=1, max_fields=0) as form:
        # Step 2: there must be exactly one item, named "file", and it must be a file
        # rather than a text field.
        submitted_items = list(form.multi_items())
        if len(submitted_items) != 1:
            raise HTTPException(400, "Upload exactly one PDF using the 'file' field.")

        field_name, uploaded_file = submitted_items[0]
        if field_name != "file" or not isinstance(uploaded_file, UploadFile):
            raise HTTPException(400, "Upload exactly one PDF using the 'file' field.")

        filename = strip_directories_from_filename(uploaded_file.filename)

        # Step 3: read the bytes, bounded by the size limit.
        pdf_bytes = await read_limited_file(uploaded_file)

        # Step 4: extract the text.
        try:
            loop = asyncio.get_running_loop()
            extracted = await loop.run_in_executor(pdf_worker, extract_pdf, pdf_bytes)
        except PDFError as error:
            # PDFError messages are written for users, so they are safe to pass on.
            # The log records sizes only, never the filename or any paper text.
            logger.info(
                "PDF upload rejected (bytes=%d, status=%d).", len(pdf_bytes), error.status_code
            )
            raise HTTPException(error.status_code, str(error)) from error
        finally:
            # Release the PDF bytes promptly; they can be up to 20 MB.
            del pdf_bytes

    # Step 5: replace this session's document only after extraction succeeds.
    document_id = str(uuid4())
    document = {"document_id": document_id, "filename": filename, **extracted}

    session_id = store_document(document, session_id)
    response.headers["Cache-Control"] = "no-store"

    readable_pages = 0
    for page in document["pages"]:
        if page["text"]:
            readable_pages += 1

    logger.info(
        "PDF extracted (document_id=%s, pages=%d, readable_pages=%d, characters=%d).",
        document_id, document["page_count"], readable_pages, document["character_count"],
    )

    return UploadResponse(
        document_id=document["document_id"],
        session_id=session_id,
        filename=document["filename"],
        page_count=document["page_count"],
        character_count=document["character_count"],
        preview=document["preview"],
    )


def raise_if_document_was_replaced(document_id: str, document: dict, message: str) -> None:
    """Abort if the user uploaded a new PDF while this request was still running.

    This is the "stale request" protection. Summaries and answers take many seconds, and
    the user may upload a different paper in the meantime. We compare object identity
    (`is not`) to confirm the stored document is still the exact same one we started
    with, so we never show the new paper an answer built from the old one.
    """
    prune_expired_documents()
    if documents.get(document_id) is not document:
        raise HTTPException(404, message)


@app.post("/api/documents/{document_id}/summary", response_model=SummaryResponse)
async def summarize_document(document_id: str, request: Request, response: Response):
    """Generate the five-section summary for a document, or return the cached one.

    The steps, in order:
      1. Find the document.
      2. Return the saved summary if we already have one (no new provider call).
      3. Refuse if a summary is already being generated (no duplicate provider call).
      4. Ask the AI providers, in order, until one returns a valid five-section summary.
      5. Check the document was not replaced while we waited, then cache and return it.
    """
    document = get_current_document(document_id, request.headers.get(SESSION_HEADER))
    response.headers["Cache-Control"] = "no-store"

    # Step 2: a repeat click costs nothing and cannot produce a different summary.
    if document.get("summary") is not None:
        return document["summary"]

    # Step 3: two requests at once would pay twice for the same summary.
    if document.get("summary_in_progress"):
        raise HTTPException(
            409, "A summary is already being generated for this document. Please wait."
        )

    document["summary_in_progress"] = True
    try:
        # Step 4: this is where Gemini, then Groq, then OpenRouter are tried.
        summary_content, model = await generate_summary(document["pages"])

        # Step 5: the user may have uploaded a replacement while we were waiting.
        raise_if_document_was_replaced(
            document_id, document,
            "This document was replaced while generating its summary. Use the current PDF.",
        )

        summary_response = SummaryResponse(
            document_id=document_id,
            summary=summary_content,
            model=model,
            source_page_count=document["page_count"],
            source_character_count=document["character_count"],
        )

        document["summary"] = summary_response
        return summary_response

    except SummaryError as error:
        # `from None` hides the original exception chain, which can contain provider
        # text. The message itself is one we wrote, so it is safe to show.
        raise HTTPException(error.status_code, str(error)) from None
    finally:
        # Always clear the flag, including on failure, so the user can retry.
        document["summary_in_progress"] = False


@app.post("/api/documents/{document_id}/chat", response_model=ChatResponse)
async def chat_with_document(document_id: str, request: ChatRequest, http_request: Request, response: Response):
    """Answer one question about a document, using passages retrieved from it.

    The steps, in order:
      1. Find the document.
      2. Work out whether this is a follow-up question needing earlier context.
      3. Return a cached answer if this exact question was already asked.
      4. Refuse if an answer is already being prepared.
      5. Build the search index once, then retrieve the relevant passages.
      6. With no relevant passages, answer honestly without calling any AI provider.
      7. Otherwise ask the providers and validate the citations.
      8. Cache the result and return it.
    """
    document = get_current_document(document_id, http_request.headers.get(SESSION_HEADER))
    response.headers["Cache-Control"] = "no-store"
    question = request.question

    # Step 2: "How many heads does it use?" needs the previous question to make sense.
    context_question = follow_up_context(question, document.get("chat_topic"))

    # Step 3: an identical question returns the saved answer, free and instant.
    cache_key = chat_cache_key(question, context_question)
    cached_answer = document.get("chat_cache", {}).get(cache_key)
    if cached_answer is not None:
        # A fresh (non-follow-up) question still becomes the current topic, so later
        # follow-ups refer to it even when this answer came from the cache.
        if context_question is None:
            document["chat_topic"] = question
        return cached_answer

    # Step 4: one question at a time per document.
    if document.get("chat_in_progress"):
        raise HTTPException(
            409, "An answer is already being prepared for this document. Please wait."
        )

    document["chat_in_progress"] = True
    try:
        # Step 5: build the index once per document and reuse it for later questions.
        if "retrieval_index" not in document:
            retrieval_index = await run_in_threadpool(build_index, document["pages"])
            raise_if_document_was_replaced(
                document_id, document, "This document was replaced. Use the current PDF."
            )
            document["retrieval_index"] = retrieval_index

        # For a follow-up, search using both questions so terms from the earlier topic
        # help find the right passages.
        if context_question is None:
            search_text = question
        else:
            search_text = question + "\n" + context_question

        # Page references in an earlier topic do not constrain the new question.
        page_numbers = {int(number) for number in PAGE_REFERENCE.findall(question)}
        passages = await run_in_threadpool(
            retrieve_chunks, document["retrieval_index"], search_text, page_numbers
        )
        raise_if_document_was_replaced(
            document_id, document, "This document was replaced. Use the current PDF."
        )

        if not passages:
            # Step 6: nothing relevant was found, so say so. No AI provider is called,
            # which means no quota is spent guessing at an unanswerable question.
            answer_response = ChatResponse(
                document_id=document_id,
                answer=INSUFFICIENT_ANSWER,
                sources=[],
                insufficient_evidence=True,
                model=None,
                context_question=context_question,
            )
        else:
            # Step 7: ask the providers; citations are validated inside generate_answer.
            answer, sources, model = await generate_answer(question, passages, context_question)
            raise_if_document_was_replaced(
                document_id, document,
                "This document was replaced while preparing the answer. Use the current PDF.",
            )
            answer_response = ChatResponse(
                document_id=document_id,
                answer=answer.answer,
                sources=sources,
                evidence=build_evidence(passages, answer.cited_chunk_ids),
                insufficient_evidence=answer.insufficient_evidence,
                model=model,
                context_question=context_question,
            )

        # Step 8: remember the answer and the current topic.
        remember_answer(document, cache_key, answer_response, question, context_question)
        return answer_response

    except ProviderError as error:
        raise HTTPException(error.status_code, str(error)) from None
    finally:
        document["chat_in_progress"] = False
