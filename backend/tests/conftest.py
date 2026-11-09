import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.main import app, documents
from backend import gemini_client

REAL_GEMINI_CLIENT = gemini_client.genai.Client


@pytest.fixture(autouse=True)
def isolate_provider_network(monkeypatch):
    """All automated tests use a dummy key and refuse real provider traffic."""
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-not-a-real-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    for name in ("GROQ_API_KEY", "GROQ_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_MODEL"):
        monkeypatch.delenv(name, raising=False)
    documents.clear()

    def no_client(**options):
        raise AssertionError("A test attempted an unmocked Gemini SDK request")

    async def no_real_http(self, request):
        raise AssertionError("A test attempted a real HTTP request")

    monkeypatch.setattr(gemini_client.genai, "Client", no_client)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_real_http)
    yield
    documents.clear()


@pytest.fixture
def mock_gemini(monkeypatch):
    """Use the actual SDK with a bounded mock HTTP transport, shared by both features."""
    def install(payload=None, status=200, handler=None):
        requests = []

        async def respond(request):
            requests.append(request)
            if handler is not None:
                return await handler(request)
            body = payload
            if body is None:
                body = {"error": {"code": status, "message": "Mock Gemini failure"}}
            return httpx.Response(status, json=body)

        def client(**options):
            http_options = options["http_options"]
            http_options.async_client_args = {
                **(http_options.async_client_args or {}),
                "transport": httpx.MockTransport(respond),
            }
            return REAL_GEMINI_CLIENT(**options)

        monkeypatch.setattr(gemini_client.genai, "Client", client)
        return requests

    return install


@pytest.fixture
def make_pdf():
    """Small real PDFs generated in memory, with optional blank pages or encryption."""
    def create(texts=("PaperLense test paper",), password=None):
        with pymupdf.open() as document:
            for text in texts:
                page = document.new_page()
                if text:
                    page.insert_text((72, 72), text)
            options = {}
            if password:
                options = {"encryption": pymupdf.PDF_ENCRYPT_AES_256,
                           "owner_pw": "owner-password", "user_pw": password}
            return document.tobytes(**options)
    return create


@pytest.fixture
def client():
    documents.clear()
    with TestClient(app) as test_client:
        yield test_client
    documents.clear()
