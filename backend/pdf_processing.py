"""Validate an uploaded PDF and pull out its text, one numbered page at a time.

The PDF is never saved to disk. It arrives as bytes, PyMuPDF reads it from memory, and
we keep only the extracted text.

The one function that matters here is extract_pdf. It runs six checks before trusting a
file, in a deliberate order: the cheap checks that need no parsing come first, so an
obviously broken file is rejected before PyMuPDF is even started.

Known limitation: this reads the text layer that a PDF already contains. A scanned paper
is just photographs of pages with no text layer, so nothing can be extracted. Reading
those would need OCR, which PaperLense does not include. extract_pdf detects this case
and says so plainly.
"""

import logging

import pymupdf

# The largest upload we accept, 20 MiB. Shared with backend/main.py, which enforces the
# same limit while the request is still arriving.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Safety limits so that one unusual PDF cannot exhaust the server's memory.
MAX_PAGES = 500
MAX_TEXT_CHARACTERS = 2_000_000

# How much extracted text the frontend preview shows.
PREVIEW_CHARACTERS = 4_000

# Every PDF begins with these bytes. This is the file's "magic number".
PDF_MAGIC_BYTES = b"%PDF-"

# Every complete PDF ends with this marker. A truncated download will be missing it.
PDF_END_MARKER = b"%%EOF"

# How far back from the end of the file we look for that marker.
END_MARKER_SEARCH_BYTES = 1024

logger = logging.getLogger(__name__)


class PDFError(ValueError):
    """A document problem we understand and can safely explain to the user.

    Every message on this class is written for a person to read and tells them what to
    do next, so backend/main.py can pass it straight through to the frontend. Anything
    we do NOT understand is never turned into a PDFError; it becomes a generic message
    instead, because an unexpected error's text could contain private information.

    status_code is the HTTP status main.py should return:
      400 empty file, 413 too large, 415 not a PDF, 422 a PDF we cannot use.
    """

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def check_bytes_look_like_a_pdf(data: bytes) -> None:
    """Run the four checks that need no PDF parsing at all.

    Doing these first means a 20 MB video renamed to .pdf is rejected in microseconds,
    without handing anything to the PDF parser.

    Raises PDFError if the bytes cannot be a usable PDF.
    """
    if not data:
        raise PDFError("This file is empty. Choose a PDF containing readable text.", 400)

    if len(data) > MAX_UPLOAD_BYTES:
        raise PDFError("This file exceeds the 20 MB (20 MiB) upload limit.", 413)

    # Check the file's actual content, not its name or the browser's claimed type, both
    # of which anyone can set to anything.
    if not data.startswith(PDF_MAGIC_BYTES):
        raise PDFError("This file is not a PDF. Choose an original PDF document.", 415)

    # A complete PDF ends with "%%EOF". Its absence means the file was cut short, which
    # is the usual sign of an interrupted download.
    last_bytes = data[-END_MARKER_SEARCH_BYTES:].rstrip()
    if PDF_END_MARKER not in last_bytes:
        raise PDFError("This PDF is incomplete or corrupted. Export a fresh copy and try again.")


def check_document_is_usable(document) -> None:
    """Run the three checks that need the PDF to be open.

    Raises PDFError if we cannot or should not read this document.
    """
    # An encrypted PDF needs a password we do not have and will not ask for.
    if document.needs_pass:
        raise PDFError("This PDF is password-protected. Upload an unlocked copy.")

    # PyMuPDF sets this when it had to guess at a damaged file's structure. The text it
    # recovers may be wrong or incomplete, so we refuse rather than summarise garbage.
    if document.is_repaired:
        raise PDFError("This PDF is damaged. Export a fresh PDF and try again.")

    if document.page_count > MAX_PAGES:
        raise PDFError("This prototype supports up to 500 pages per PDF.", 413)


def build_preview(pages: list[dict]) -> str:
    """Build the short labelled extract the frontend shows after upload.

    Pages with no text are skipped here, because a preview of blank pages would be
    useless. The stored pages list still contains them, so page numbering stays correct.
    """
    preview = ""

    for page in pages:
        if page["text"]:
            preview += f"Page {page['page_number']}\n{page['text']}\n\n"
        if len(preview) >= PREVIEW_CHARACTERS:
            break

    return preview[:PREVIEW_CHARACTERS].rstrip()


def extract_pdf(data: bytes) -> dict:
    """Validate PDF bytes and return the document's text, page by page.

    Input:  data - the raw bytes of the uploaded file.
    Returns a dict with:
        page_count      - how many pages the PDF has.
        character_count - how many characters of text were extracted in total.
        pages           - [{"page_number": 1, "text": "..."}, ...] for EVERY page,
                          including pages with no text, so page numbers stay accurate.
        preview         - a short labelled extract for the frontend.
    Raises PDFError for any file we cannot use, always with a message explaining why.
    """
    check_bytes_look_like_a_pdf(data)

    # Tracks which page we were on, so that if PyMuPDF fails we can log the page number
    # without logging any of the page's actual content.
    page_number = None

    try:
        # stream=data reads the PDF straight from memory, so nothing touches the disk.
        # `with` guarantees PyMuPDF releases the document even if extraction fails.
        with pymupdf.open(stream=data, filetype="pdf") as document:
            check_document_is_usable(document)

            pages = []
            character_count = 0

            for page_number, page in enumerate(document, start=1):
                # sort=True asks PyMuPDF to return text in reading order rather than the
                # order the shapes happen to be stored in. It helps a lot with
                # two-column papers, though complex layouts are still imperfect.
                text = page.get_text("text", sort=True).strip()

                character_count += len(text)
                if character_count > MAX_TEXT_CHARACTERS:
                    raise PDFError(
                        "This PDF exceeds the prototype's 2 million character limit.", 413
                    )

                # Blank pages are kept with empty text on purpose. Dropping them would
                # shift every later page number and break citations.
                pages.append({"page_number": page_number, "text": text})

            # No text anywhere means a scanned or image-only PDF.
            if not character_count:
                raise PDFError(
                    "No readable text was found. Scanned or image-only PDFs need OCR, "
                    "which PaperLense does not provide. Try a PDF with selectable text."
                )

            return {
                "page_count": document.page_count,
                "character_count": character_count,
                "pages": pages,
                "preview": build_preview(pages),
            }

    except PDFError:
        # Already a clear, user-safe message. Pass it straight through.
        raise
    except (RuntimeError, ValueError) as error:
        # PyMuPDF failed in a way we did not anticipate. Log the page number and the
        # exception TYPE only: the message itself could contain text from the paper.
        logger.warning(
            "PDF parser failed (page=%s, error_type=%s).", page_number, type(error).__name__
        )
        raise PDFError(
            "This PDF could not be read. It may be corrupted. Try a fresh copy."
        ) from error
