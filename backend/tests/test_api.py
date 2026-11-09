import asyncio
import logging
import threading
from uuid import UUID

import httpx
import pytest
from starlette.datastructures import UploadFile
from io import BytesIO

from backend import main
from backend.main import documents, read_limited_file
from backend.pdf_processing import MAX_UPLOAD_BYTES


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_uploads_share_one_pdf_worker_without_blocking_health(make_pdf, monkeypatch):
    data = make_pdf()
    release_parser = threading.Event()
    worker_ids = []
    real_extract = main.extract_pdf

    async def exercise():
        loop = asyncio.get_running_loop()
        first_started = asyncio.Event()

        def extract(data):
            worker_ids.append(threading.get_ident())
            if len(worker_ids) == 1:
                loop.call_soon_threadsafe(first_started.set)
                assert release_parser.wait(timeout=5)
            return real_extract(data)

        monkeypatch.setattr(main, "extract_pdf", extract)
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"file": ("paper.pdf", data)}
            first = asyncio.create_task(client.post("/api/upload", files=files))
            second = None
            try:
                await asyncio.wait_for(first_started.wait(), timeout=3)
                second = asyncio.create_task(client.post("/api/upload", files=files))
                health = await asyncio.wait_for(client.get("/api/health"), timeout=3)
                assert health.status_code == 200
            finally:
                release_parser.set()
                first_response = await first
                if second is not None:
                    second_response = await second
            assert first_response.status_code == second_response.status_code == 201
            assert len(worker_ids) == 2 and worker_ids[0] == worker_ids[1]

    asyncio.run(exercise())


def test_upload_returns_real_metadata_and_stores_numbered_pages(client, make_pdf):
    response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf(("Research", "Results")), "application/pdf")})
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {"document_id", "filename", "page_count", "character_count", "preview"}
    assert UUID(result["document_id"]).version == 4
    assert result["filename"] == "paper.pdf"
    assert result["page_count"] == 2
    assert result["character_count"] == len("ResearchResults")
    assert "Results" in result["preview"]
    assert documents[result["document_id"]]["pages"][1] == {"page_number": 2, "text": "Results"}


@pytest.mark.parametrize("name,mime", [("paper.txt", "text/plain"), ("paper.pdf", "application/octet-stream")])
def test_content_is_validated_independently_of_metadata(client, make_pdf, name, mime):
    response = client.post("/api/upload", files={"file": (name, make_pdf(), mime)})
    assert response.status_code == 201


@pytest.mark.parametrize("data,status", [(b"fake PDF", 415), (b"%PDF-1.7\nbroken\n%%EOF", 422), (b"", 400)])
def test_invalid_upload_is_safe_and_not_stored(client, data, status):
    response = client.post("/api/upload", files={"file": ("fake.pdf", data, "application/pdf")})
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    assert not documents


@pytest.mark.parametrize("kind,phrase", [("blank", "OCR"), ("encrypted", "password-protected")])
def test_unsupported_pdfs_have_actionable_errors(client, make_pdf, kind, phrase):
    data = make_pdf(("",)) if kind == "blank" else make_pdf(password="secret")
    response = client.post("/api/upload", files={"file": ("paper.pdf", data, "application/pdf")})
    assert response.status_code == 422
    assert phrase in response.json()["detail"]


@pytest.mark.parametrize("extra_bytes", [1, 70 * 1024])
def test_oversized_file_and_request_are_rejected(client, extra_bytes):
    response = client.post("/api/upload", files={"file": ("large.pdf", b"x" * (MAX_UPLOAD_BYTES + extra_bytes), "application/pdf")})
    assert response.status_code == 413
    assert "20 MB" in response.json()["detail"]
    assert not documents


def test_streamed_request_without_content_length_is_bounded(client):
    def body():
        for _ in range(22):
            yield b"x" * (1024 * 1024)
    response = client.post("/api/upload", content=body(), headers={"content-type": "multipart/form-data; boundary=example"})
    assert response.status_code == 413


def test_exact_file_size_limit_is_accepted(client, make_pdf):
    data = make_pdf()
    # Keep startxref and EOF together at the end; pad after the trailer instead.
    data = data.replace(b"startxref", b" " * (MAX_UPLOAD_BYTES - len(data)) + b"startxref")
    assert len(data) == MAX_UPLOAD_BYTES
    response = client.post("/api/upload", files={"file": ("boundary.pdf", data, "application/pdf")})
    assert response.status_code == 201


@pytest.mark.parametrize("files", [[], [("wrong", ("paper.pdf", b"x"))],
    [("file", ("one.pdf", b"x")), ("file", ("two.pdf", b"x"))],
    [("file", ("one.pdf", b"x")), ("extra", ("two.pdf", b"x"))]])
def test_accepts_exactly_one_named_file(client, files):
    response = client.post("/api/upload", files=files)
    assert response.status_code in (400, 415)


def test_extra_text_fields_are_rejected(client, make_pdf):
    response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf())}, data={"extra": "no"})
    assert response.status_code == 400


def test_store_replaces_previous_document_only_on_success(client, make_pdf):
    first = client.post("/api/upload", files={"file": ("first.pdf", make_pdf())}).json()
    client.post("/api/upload", files={"file": ("bad.pdf", b"bad")})
    assert list(documents) == [first["document_id"]]
    second = client.post("/api/upload", files={"file": ("second.pdf", make_pdf(("Second document",)))}).json()
    assert second["document_id"] != first["document_id"]
    assert list(documents) == [second["document_id"]]


def test_filename_does_not_expose_client_path(client, make_pdf):
    result = client.post("/api/upload", files={"file": ("C:/private/folder/paper.pdf", make_pdf())}).json()
    assert result["filename"] == "paper.pdf"


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://localhost:4173"])
def test_cors_allows_upload_response_for_local_frontend(client, make_pdf, origin):
    allowed = client.options("/api/upload", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == origin
    uploaded = client.post("/api/upload", headers={"Origin": origin}, files={"file": ("paper.pdf", make_pdf())})
    assert uploaded.status_code == 201
    assert uploaded.headers["access-control-allow-origin"] == origin
    document_id = uploaded.json()["document_id"]
    assert UUID(document_id).version == 4
    assert document_id in documents


def test_cors_rejects_untrusted_origin(client):
    rejected = client.options("/api/upload", headers={"Origin": "https://example.com", "Access-Control-Request-Method": "POST"})
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_extraction_logs_counts_without_filename_or_paper_text(client, make_pdf, caplog):
    caplog.set_level(logging.INFO, logger="backend.main")
    response = client.post("/api/upload", files={"file": ("private-name.pdf", make_pdf(("private text", "")))})
    assert response.status_code == 201
    assert response.json()["document_id"] in caplog.text
    assert "pages=2, readable_pages=1, characters=12" in caplog.text
    assert "private-name.pdf" not in caplog.text
    assert "private text" not in caplog.text


def test_unexpected_failure_does_not_leak_internal_details(make_pdf, monkeypatch):
    from fastapi.testclient import TestClient
    def fail(data):
        raise RuntimeError("secret internal path C:/private")
    monkeypatch.setattr(main, "extract_pdf", fail)
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf())})
    assert response.status_code == 500
    assert "secret" not in response.text
    assert "try again" in response.json()["detail"]


def test_unexpected_failure_is_contained_without_logging_private_data(client, make_pdf, monkeypatch, caplog):
    def fail(data):
        raise RuntimeError("PRIVATE PAPER CONTENT unit-test-not-a-real-key")
    monkeypatch.setattr(main, "extract_pdf", fail)
    # Default TestClient re-raises uncontained errors, just as an ASGI server logs them.
    response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf())},
                           headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "RuntimeError" in caplog.text
    assert "PRIVATE PAPER" not in response.text + caplog.text
    assert "unit-test-not-a-real-key" not in response.text + caplog.text
    assert client.get("/api/health").status_code == 200


def test_limited_reader_stops_at_limit_plus_one(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    file = UploadFile(file=BytesIO(b"x" * 100), filename="large.pdf")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(read_limited_file(file))
    assert caught.value.status_code == 413
    assert file.file.tell() == 11
