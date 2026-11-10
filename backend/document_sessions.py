"""One temporary document per browser session, held by a single backend process."""

import re
from secrets import compare_digest, token_urlsafe
from time import monotonic

from fastapi import HTTPException

SESSION_HEADER = "X-PaperLens-Session"
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
DOCUMENT_TTL_SECONDS = 30 * 60
MAX_DOCUMENTS = 8
MAX_STORED_CHARACTERS = 4_000_000
DOCUMENT_UNAVAILABLE = "This document is no longer available. Upload the PDF again."

documents: dict[str, dict] = {}


def prune_expired_documents() -> None:
    now = monotonic()
    for document_id, document in list(documents.items()):
        if document["expires_at"] <= now:
            del documents[document_id]


def validate_upload_session(session_id: str | None) -> None:
    if session_id is not None and not SESSION_TOKEN.fullmatch(session_id):
        raise HTTPException(400, "Invalid browser session. Reload the page and upload the PDF again.")


def store_document(document: dict, session_id: str | None) -> str:
    prune_expired_documents()
    previous = None
    if session_id is not None:
        for stored in documents.values():
            if compare_digest(stored["session_id"], session_id):
                previous = stored
                break

    # Count capacity before removing anything. A rejected upload leaves every paper intact.
    retained = [stored for stored in documents.values() if stored is not previous]
    total_characters = document["character_count"] + sum(item["character_count"] for item in retained)
    if len(retained) >= MAX_DOCUMENTS or total_characters > MAX_STORED_CHARACTERS:
        raise HTTPException(503, "Document storage is full. Please try uploading again later.")

    if previous is not None:
        del documents[previous["document_id"]]
        session_id = previous["session_id"]
    else:
        # An expired or unknown token can start a new session, but cannot choose its ID.
        session_id = token_urlsafe(32)
    document["session_id"] = session_id
    document["expires_at"] = monotonic() + DOCUMENT_TTL_SECONDS
    documents[document["document_id"]] = document
    return session_id


def get_current_document(document_id: str, session_id: str | None) -> dict:
    prune_expired_documents()
    document = documents.get(document_id)
    if (document is None or session_id is None or not SESSION_TOKEN.fullmatch(session_id)
            or not compare_digest(document["session_id"], session_id)):
        # Use the same response for missing, expired and foreign documents.
        raise HTTPException(404, DOCUMENT_UNAVAILABLE)
    return document
