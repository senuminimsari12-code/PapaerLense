"""Exercise provider failover through the API with all remote traffic mocked."""

import asyncio
import json

import httpx
import pytest

from backend import gemini_client, main, summarization
from backend.main import documents
from backend.http_error_messages import provider_error_for_status
from backend.summarization import PaperSummary

GROQ_MODEL = "openai/gpt-oss-120b"
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
GROQ_KEY = "dummy-groq-credential"
OPENROUTER_KEY = "dummy-openrouter-credential"
SUMMARY = {
    "title_authors_abstract": "A classifier evaluation by Example Author.",
    "problem_statement": "The work measures classification accuracy.",
    "methodology": "The classifier was tested on images.",
    "key_results": "The classifier attained 93 percent accuracy.",
    "conclusion": "The result applies to the evaluated dataset.",
}
ANSWER = {
    "answer": "The image classifier attained 93 percent accuracy. [Page 2]",
    "cited_chunk_ids": ["chunk-1"],
    "insufficient_evidence": False,
}
NO_EVIDENCE = {
    "answer": "The requested answer is not supported.",
    "cited_chunk_ids": [],
    "insufficient_evidence": True,
}
PAPER = ("", "The image classifier attained 93 percent accuracy.",
         "Volcanic eruptions release lava and ash through vents.")
QUESTION = "What accuracy does the image classifier achieve?"


@pytest.fixture
def mock_providers(monkeypatch, mock_gemini):
    """Install the real SDK and HTTPX request paths with recorded fake responses."""
    monkeypatch.setenv("GROQ_API_KEY", GROQ_KEY)
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)

    def install(*, gemini=SUMMARY, groq=SUMMARY, openrouter=SUMMARY):
        plans = {"gemini": gemini, "groq": groq, "openrouter": openrouter}
        calls = []

        async def respond(provider, request):
            calls.append((provider, request))
            output = plans[provider]
            if callable(output):
                output = await output(request)
            if isinstance(output, int):
                # An upstream body must never leak into logs or API errors.
                return httpx.Response(output, json={
                    "error": {"code": output, "message": f"private body {GROQ_KEY}"},
                })
            content = output if isinstance(output, str) else json.dumps(output)
            if provider == "gemini":
                return httpx.Response(200, json={"candidates": [{
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": content}]},
                }]})
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }]})

        async def gemini_response(request):
            return await respond("gemini", request)

        async def backup_response(self, request):
            routes = {
                "https://api.groq.com/openai/v1/chat/completions": ("groq", GROQ_KEY),
                "https://openrouter.ai/api/v1/chat/completions": ("openrouter", OPENROUTER_KEY),
            }
            provider, key = routes[str(request.url)]
            assert request.method == "POST"
            assert request.headers["Authorization"] == f"Bearer {key}"
            assert key not in request.content.decode()
            return await respond(provider, request)

        mock_gemini(handler=gemini_response)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", backup_response)
        return calls

    return install


def upload(client, make_pdf):
    response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf(PAPER))})
    assert response.status_code == 201
    return response.json()["document_id"]


@pytest.mark.parametrize("primary,backup,providers,model", [
    (SUMMARY, SUMMARY, ["gemini"], gemini_client.DEFAULT_MODEL),
    (503, SUMMARY, ["gemini", "groq"], GROQ_MODEL),
    (504, SUMMARY, ["gemini", "groq"], GROQ_MODEL),
    (503, 503, ["gemini", "groq", "openrouter"], OPENROUTER_MODEL),
    (429, 429, ["gemini", "groq", "openrouter"], OPENROUTER_MODEL),
    (401, SUMMARY, ["gemini", "groq"], GROQ_MODEL),
    (404, SUMMARY, ["gemini", "groq"], GROQ_MODEL),
    ("not valid JSON", SUMMARY, ["gemini", "groq"], GROQ_MODEL),
    (503, {"problem_statement": "incomplete"}, ["gemini", "groq", "openrouter"], OPENROUTER_MODEL),
])
def test_summary_failover_is_ordered_and_cached(client, make_pdf, mock_providers, primary, backup, providers, model):
    calls = mock_providers(gemini=primary, groq=backup)
    document_id = upload(client, make_pdf)
    assert calls == []
    endpoint = f"/api/documents/{document_id}/summary"
    result = client.post(endpoint)
    assert result.status_code == 200
    assert result.json()["summary"] == SUMMARY
    assert list(result.json()["summary"]) == list(PaperSummary.model_fields)
    assert result.json()["model"] == model
    assert client.post(endpoint).json() == result.json()
    assert [provider for provider, _ in calls] == providers
    for provider, request in calls:
        if provider == "openrouter":
            assert "response_format" not in json.loads(request.content)


def test_missing_providers_are_skipped_without_requests(client, make_pdf, mock_providers, monkeypatch):
    calls = mock_providers()
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.delenv("GROQ_API_KEY")
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == OPENROUTER_MODEL
    assert [provider for provider, _ in calls] == ["openrouter"]


def test_key_in_model_setting_is_never_sent_or_exposed(client, make_pdf, mock_providers, monkeypatch, caplog):
    calls = mock_providers(gemini=503)
    monkeypatch.setenv("GROQ_MODEL", GROQ_KEY)
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == OPENROUTER_MODEL
    assert [provider for provider, _ in calls] == ["gemini", "openrouter"]
    assert GROQ_KEY not in caplog.text + result.text


def test_all_failures_are_safe_and_leave_document_available(client, make_pdf, mock_providers, caplog):
    calls = mock_providers(gemini=503, groq=401, openrouter=503)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 503
    assert response.json()["detail"]
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]
    for provider, _ in calls:
        assert provider in caplog.text.casefold()
    assert GROQ_KEY not in caplog.text + response.text
    assert OPENROUTER_KEY not in caplog.text + response.text
    assert "private body" not in caplog.text + response.text
    assert document_id in documents
    assert not documents[document_id]["summary_in_progress"]
    assert "summary" not in documents[document_id]


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failure_switches_provider(client, make_pdf, mock_providers, failure):
    async def fail(request):
        raise failure("private transport details", request=request)

    calls = mock_providers(gemini=503, groq=fail)
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == OPENROUTER_MODEL
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]


def test_slow_primary_is_cancelled_before_backup_uses_remaining_budget(client, make_pdf, mock_providers, monkeypatch):
    primary_cancelled = False

    async def slow_primary(request):
        nonlocal primary_cancelled
        try:
            await asyncio.sleep(10)
        finally:
            primary_cancelled = True

    async def backup(request):
        assert primary_cancelled
        return SUMMARY

    monkeypatch.setattr(summarization, "SUMMARY_TIMEOUT_SECONDS", 1)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    calls = mock_providers(gemini=slow_primary, groq=backup)
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == GROQ_MODEL
    assert [provider for provider, _ in calls] == ["gemini", "groq"]


def test_chat_retrieves_once_and_preserves_evidence_and_citations(client, make_pdf, mock_providers, monkeypatch):
    forged = {**ANSWER, "answer": "This should be rejected. [Page 999]"}
    calls = mock_providers(gemini=503, groq=forged, openrouter=ANSWER)
    original_retrieve = main.retrieve_chunks
    queries = []

    def retrieve(index, query):
        queries.append(query)
        return original_retrieve(index, query)

    monkeypatch.setattr(main, "retrieve_chunks", retrieve)
    document_id = upload(client, make_pdf)
    endpoint = f"/api/documents/{document_id}/chat"
    prior = client.post(endpoint, json={"question": "How do I bake sourdough bread?"})
    assert prior.json()["insufficient_evidence"]
    assert not calls
    queries.clear()
    response = client.post(endpoint, json={"question": QUESTION})
    assert response.status_code == 200
    result = response.json()
    assert result["model"] == OPENROUTER_MODEL
    assert result["answer"] == ANSWER["answer"]
    assert result["sources"] == [{"chunk_id": "chunk-1", "page_number": 2, "excerpt": PAPER[1]}]
    assert result["context_question"] is None
    assert queries == [QUESTION]
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]
    gemini, groq, openrouter = [json.loads(request.content) for _, request in calls]
    original = json.loads(gemini["contents"][0]["parts"][0]["text"])
    assert original == {"question": QUESTION, "context_question": None, "passages": [
        {"chunk_id": "chunk-1", "page_number": 2, "text": PAPER[1]},
    ]}
    for body in (groq, openrouter):
        assert json.loads(next(message["content"] for message in body["messages"] if message["role"] == "user")) == original


def test_honest_no_evidence_response_does_not_fail_over(client, make_pdf, mock_providers):
    calls = mock_providers(gemini=NO_EVIDENCE)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/chat", json={"question": QUESTION})
    assert response.status_code == 200
    assert response.json()["insufficient_evidence"]
    assert response.json()["sources"] == []
    assert [provider for provider, _ in calls] == ["gemini"]


def test_invalid_upload_and_missing_document_never_contact_providers(client, mock_providers):
    calls = mock_providers()
    assert client.post("/api/upload", files={"file": ("invalid.pdf", b"wrong")}).status_code == 415
    assert client.post("/api/documents/missing/summary").status_code == 404
    assert client.post("/api/documents/missing/chat", json={"question": QUESTION}).status_code == 404
    assert calls == []


def test_in_flight_failover_summary_rejects_a_duplicate(make_pdf, mock_providers):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def groq_response(request):
            started.set()
            await release.wait()
            return SUMMARY

        calls = mock_providers(gemini=503, groq=groq_response)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            uploaded = await client.post("/api/upload", files={"file": ("paper.pdf", make_pdf(PAPER))})
            endpoint = f"/api/documents/{uploaded.json()['document_id']}/summary"
            pending = asyncio.create_task(client.post(endpoint))
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                assert (await client.post(endpoint)).status_code == 409
            finally:
                release.set()
                result = await pending
            assert result.status_code == 200
            assert [provider for provider, _ in calls] == ["gemini", "groq"]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Bug 3 regression: HTTP 413 used to be reported as a configuration error.
#
# Groq's free tier rejects a full-length paper with HTTP 413 while OpenRouter accepts
# the same paper. The old mapping called that "the provider rejected the configured
# model or request", which wrongly suggested a broken API key or model name.
# ---------------------------------------------------------------------------


def test_413_is_classified_as_a_request_size_limit_not_a_configuration_error():
    error = provider_error_for_status(413)
    assert error.category == "payload_too_large"
    assert error.status_code == 413
    assert error.upstream_status == 413
    # The message must talk about size, not about credentials or model configuration.
    assert "size limit" in str(error)
    assert "credential" not in str(error).casefold()
    assert "model" not in str(error).casefold()


def test_413_classification_differs_from_the_other_statuses():
    # A guard against 413 silently falling through to the catch-all branch again.
    assert provider_error_for_status(400).category == "configuration"
    assert provider_error_for_status(404).category == "configuration"
    assert provider_error_for_status(413).category == "payload_too_large"


def test_groq_413_falls_over_to_openrouter(client, make_pdf, mock_providers, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    calls = mock_providers(groq=413, openrouter=SUMMARY)
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["summary"] == SUMMARY
    assert result.json()["model"] == OPENROUTER_MODEL
    # Groq is attempted exactly once, then OpenRouter completes the request.
    assert [provider for provider, _ in calls] == ["groq", "openrouter"]


def test_gemini_failure_then_groq_413_then_openrouter_success(client, make_pdf, mock_providers):
    calls = mock_providers(gemini=503, groq=413, openrouter=SUMMARY)
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == OPENROUTER_MODEL
    # Correct order, and exactly one attempt per provider: no retries of any kind.
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]
    assert len(calls) == 3


def test_groq_413_is_logged_as_a_size_limit_without_leaking_the_body(client, make_pdf, mock_providers, caplog):
    calls = mock_providers(gemini=503, groq=413, openrouter=SUMMARY)
    document_id = upload(client, make_pdf)
    assert client.post(f"/api/documents/{document_id}/summary").status_code == 200
    assert "category=payload_too_large" in caplog.text
    assert "upstream_code=413" in caplog.text
    # The provider's own response body must never reach the log.
    assert "private body" not in caplog.text
    assert GROQ_KEY not in caplog.text
    assert len(calls) == 3


def test_413_from_every_provider_explains_the_size_limit_safely(client, make_pdf, mock_providers, caplog):
    calls = mock_providers(gemini=413, groq=413, openrouter=413)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 413
    detail = response.json()["detail"]
    # A clear explanation, and no suggestion that simply retrying would help.
    assert "larger than the configured AI providers" in detail
    assert "shorter paper" in detail
    assert "was not shortened" in detail
    # Each provider tried once, in order, with no retry loop.
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]
    assert len(calls) == 3
    # The upload survives, so the user can try a shorter paper without re-uploading.
    assert document_id in documents
    assert "summary" not in documents[document_id]
    assert not documents[document_id]["summary_in_progress"]
    assert GROQ_KEY not in caplog.text + response.text
    assert OPENROUTER_KEY not in caplog.text + response.text


@pytest.mark.parametrize("groq_status, expected_status", [(503, 503), (429, 429)])
def test_final_413_does_not_hide_other_provider_failures(
    client, make_pdf, mock_providers, groq_status, expected_status
):
    calls = mock_providers(gemini=504, groq=groq_status, openrouter=413)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")

    assert response.status_code == expected_status
    assert "could not complete" in response.json()["detail"]
    assert "shorter paper" not in response.json()["detail"]
    assert [provider for provider, _ in calls] == ["gemini", "groq", "openrouter"]
    assert document_id in documents
    assert "summary" not in documents[document_id]


def test_413_does_not_stop_a_later_summary_from_succeeding(client, make_pdf, mock_providers):
    # The 413 must not be cached or remembered as a permanent failure.
    calls = mock_providers(gemini=413, groq=413, openrouter=413)
    document_id = upload(client, make_pdf)
    assert client.post(f"/api/documents/{document_id}/summary").status_code == 413
    assert len(calls) == 3

    calls.clear()
    mock_providers(gemini=413, groq=413, openrouter=SUMMARY)
    result = client.post(f"/api/documents/{document_id}/summary")
    assert result.status_code == 200
    assert result.json()["model"] == OPENROUTER_MODEL
