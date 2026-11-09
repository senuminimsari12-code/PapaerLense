"""Exercise the Gemini SDK through a mock HTTP transport; never use credits."""

import asyncio
import json

import httpx
import pytest

from backend import gemini_client, main, summarization
from backend.main import documents
from backend.summarization import PaperSummary, SummaryError, build_paper_text

REAL_ASYNC_CLIENT = httpx.AsyncClient
TEST_SUMMARY = {
    "title_authors_abstract": "Fixture paper by Example Author. The paper studies a test method.",
    "problem_statement": "The paper investigates a specified research question.",
    "methodology": "The authors compare two methods on their reported dataset.",
    "key_results": "The paper reports an improvement of 2 percentage points.",
    "conclusion": "The findings apply to the tested setting. Further validation is not reported.",
}


def provider_payload(content=None):
    return {"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
        {"text": json.dumps(TEST_SUMMARY if content is None else content)}
    ]}}]}


@pytest.fixture
def mock_provider(mock_gemini):
    def install(handler=None, status=200, payload=None):
        if payload is None and status == 200:
            payload = provider_payload()
        return mock_gemini(payload=payload, status=status, handler=handler)

    return install


def upload(client, make_pdf, texts=("A test paper with meaningful text.",)):
    response = client.post("/api/upload", files={"file": ("paper.pdf", make_pdf(texts))})
    assert response.status_code == 201
    return response.json()["document_id"]


def test_missing_document_returns_404_without_provider_call(client):
    for document_id in ("missing-document", "d806686a-946e-4575-af7d-d0f598b311d3"):
        response = client.post(f"/api/documents/{document_id}/summary")
        assert response.status_code == 404
        assert "Upload the PDF again" in response.json()["detail"]


def test_full_text_and_original_page_numbers_go_to_provider(client, make_pdf, mock_provider):
    requests = mock_provider()
    document_id = upload(client, make_pdf, ("First page", "", "Last page findings"))
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 200
    result = response.json()
    assert result["document_id"] == document_id
    assert result["summary"] == TEST_SUMMARY
    assert list(result["summary"]) == list(PaperSummary.model_fields)
    assert result["source_page_count"] == 3
    assert result["source_character_count"] == len("First pageLast page findings")
    assert result["model"] == gemini_client.DEFAULT_MODEL
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert str(request.url) == f"{gemini_client.GEMINI_API_URL}/v1beta/models/{gemini_client.DEFAULT_MODEL}:generateContent"
    assert request.headers["x-goog-api-key"] == "unit-test-not-a-real-key"
    assert "unit-test-not-a-real-key" not in str(request.url)
    assert "unit-test-not-a-real-key" not in request.content.decode()
    assert body["contents"][0]["parts"][0]["text"] == "Page 1\nFirst page\n\nPage 2\n\n\nPage 3\nLast page findings"
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["required"] == list(TEST_SUMMARY)
    assert config["responseJsonSchema"]["additionalProperties"] is False
    assert config["candidateCount"] == 1
    assert config["thinkingConfig"]["include_thoughts"] is False
    assert config["thinkingConfig"]["thinking_level"] == "LOW"
    instructions = body["systemInstruction"]["parts"][0]["text"]
    assert "untrusted source material" in instructions
    assert "Never invent authors" in instructions
    assert "Not reported in the supplied paper" in instructions
    assert "unit-test-not-a-real-key" not in response.text


def test_summary_uses_all_text_instead_of_the_preview(client, make_pdf, mock_provider):
    requests = mock_provider()
    document_id = upload(client, make_pdf, tuple(f"Research page {i}: " + "word " * 30 for i in range(60)))
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 200
    sent = json.loads(requests[0].content)["contents"][0]["parts"][0]["text"]
    assert "Research page 59" in sent
    assert len(sent) > len(documents[document_id]["preview"])


@pytest.mark.parametrize("value", [None, "", "   ", "your_gemini_api_key_here"])
def test_missing_or_placeholder_key_is_actionable(client, make_pdf, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("GEMINI_API_KEY", value)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]
    assert "restart the backend" in response.json()["detail"]
    assert documents[document_id]["summary_in_progress"] is False
    assert "summary" not in documents[document_id]


def test_model_is_read_from_backend_environment(client, make_pdf, monkeypatch, mock_provider):
    monkeypatch.setenv("GEMINI_MODEL", "configured-compatible-model")
    requests = mock_provider()
    document_id = upload(client, make_pdf)
    result = client.post(f"/api/documents/{document_id}/summary").json()
    assert result["model"] == "configured-compatible-model"
    assert requests[0].url.path.endswith("/models/configured-compatible-model:generateContent")


@pytest.mark.parametrize("status,expected,phrase", [
    (401, 503, "credentials"), (403, 503, "credentials"), (429, 429, "quota"),
    (500, 503, "temporarily unavailable"), (503, 503, "temporarily unavailable"),
    (400, 502, "GEMINI_MODEL"), (404, 502, "GEMINI_MODEL"),
    (408, 504, "timed out"), (504, 504, "timed out"),
])
def test_provider_errors_are_safe(client, make_pdf, mock_provider, status, expected, phrase, caplog):
    requests = mock_provider(status=status, payload={"error": {"code": status, "message": "PRIVATE RESEARCH TEXT unit-test-not-a-real-key"}})
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == expected
    assert phrase in response.json()["detail"]
    assert "PRIVATE RESEARCH" not in response.text + caplog.text
    assert "unit-test-not-a-real-key" not in response.text + caplog.text
    assert documents[document_id]["summary_in_progress"] is False
    assert len(requests) == 1  # SDK automatic retries must remain disabled.


@pytest.mark.parametrize("exception,status", [(httpx.ReadTimeout, 504), (httpx.ConnectTimeout, 504), (httpx.ConnectError, 503)])
def test_provider_network_failures(client, make_pdf, mock_provider, exception, status):
    async def fail(request):
        raise exception("private transport details", request=request)
    mock_provider(handler=fail)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == status
    assert "private transport" not in response.text


@pytest.mark.parametrize("provider_status,logged_status", [
    ("UNAVAILABLE", "UNAVAILABLE"), ("unit-test-not-a-real-key", "UNCLASSIFIED"),
    (["unit-test-not-a-real-key"], "UNCLASSIFIED"),
])
def test_provider_diagnostics_log_only_allowlisted_status(client, make_pdf, mock_provider, caplog, provider_status, logged_status):
    mock_provider(status=503, payload={"error": {"code": 503, "status": provider_status,
                                               "message": "PRIVATE TEXT unit-test-not-a-real-key"}})
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 503
    assert f"HTTP 503; status {logged_status}" in caplog.text
    assert "PRIVATE TEXT" not in caplog.text + response.text
    assert "unit-test-not-a-real-key" not in caplog.text + response.text


def test_total_deadline_bounds_even_a_slow_provider(client, make_pdf, monkeypatch, mock_provider):
    monkeypatch.setattr(summarization, "SUMMARY_TIMEOUT_SECONDS", 0.01)
    async def slow(request):
        await asyncio.sleep(10)
        return httpx.Response(200, json=provider_payload())
    mock_provider(handler=slow)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 504
    assert documents[document_id]["summary_in_progress"] is False


@pytest.mark.parametrize("content", [
    {}, {"problem_statement": "Only one field"}, {**TEST_SUMMARY, "methodology": "   "},
    {**TEST_SUMMARY, "key_results": ["wrong type"]}, {**TEST_SUMMARY, "conclusion": "x" * 12_001},
    {**TEST_SUMMARY, "unexpected_field": "not allowed"}, ["an array"],
])
def test_invalid_summary_fields_are_rejected(client, make_pdf, mock_provider, content):
    mock_provider(payload=provider_payload(content))
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 502
    assert "invalid or incomplete summary" in response.json()["detail"]
    assert "summary" not in documents[document_id]


@pytest.mark.parametrize("payload", [
    {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "incomplete"}]}}]},
    {"candidates": [{"finishReason": "SAFETY", "finishMessage": "private details"}]},
    {"candidates": []}, {"candidates": None}, {"candidates": [None]},
    {"candidates": [{"finishReason": "STOP", "content": None}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not JSON"}]}}]},
    {"promptFeedback": {"blockReason": "SAFETY", "blockReasonMessage": "private details"}},
    [],
])
def test_invalid_envelopes_incomplete_output_and_refusals(client, make_pdf, mock_provider, payload):
    mock_provider(payload=payload)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 502
    assert "private details" not in response.text


def test_provider_non_json_body_is_safe(client, make_pdf, mock_provider):
    async def non_json(request):
        return httpx.Response(200, text="<html>private provider failure</html>")
    mock_provider(handler=non_json)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 502
    assert "unreadable response" in response.json()["detail"]


def test_gemini_does_not_forward_credentials_or_paper_on_redirect(client, make_pdf, mock_provider):
    async def redirect(request):
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(307, headers={"Location": "https://untrusted.example/redirect"})
        return httpx.Response(200, json=provider_payload())

    requests = mock_provider(handler=redirect)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")

    assert [request.url.host for request in requests] == ["generativelanguage.googleapis.com"]
    assert requests[0].headers["x-goog-api-key"] == "unit-test-not-a-real-key"
    assert response.status_code == 502
    assert "untrusted.example" not in response.text


def test_thinking_is_not_exposed_and_fragmented_json_is_joined(client, make_pdf, mock_provider):
    text = json.dumps(TEST_SUMMARY)
    payload = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"thought": True, "text": "private model reasoning"},
        {"text": text[:50]}, {"text": text[50:]},
    ]}}]}
    mock_provider(payload=payload)
    document_id = upload(client, make_pdf)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 200
    assert response.json()["summary"] == TEST_SUMMARY
    assert "private model reasoning" not in response.text


def test_multiple_candidates_are_rejected(client, make_pdf, mock_provider):
    payload = provider_payload()
    payload["candidates"] *= 2
    mock_provider(payload=payload)
    document_id = upload(client, make_pdf)
    assert client.post(f"/api/documents/{document_id}/summary").status_code == 502


def test_retry_after_failure_and_success_cache(client, make_pdf, mock_provider):
    mock_provider(status=503)
    document_id = upload(client, make_pdf)
    assert client.post(f"/api/documents/{document_id}/summary").status_code == 503
    requests = mock_provider()
    first = client.post(f"/api/documents/{document_id}/summary")
    second = client.post(f"/api/documents/{document_id}/summary")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(requests) == 1


def test_replaced_document_cannot_use_old_cached_summary(client, make_pdf, mock_provider):
    mock_provider()
    first = upload(client, make_pdf)
    assert client.post(f"/api/documents/{first}/summary").status_code == 200
    second = upload(client, make_pdf, ("Replacement paper",))
    assert client.post(f"/api/documents/{first}/summary").status_code == 404
    assert "summary" not in documents[second]


@pytest.mark.parametrize("replace_document", [False, True])
def test_in_flight_duplicate_or_replacement_does_not_corrupt_state(make_pdf, mock_provider, replace_document):
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        async def wait_for_release(request):
            started.set()
            await release.wait()
            return httpx.Response(200, json=provider_payload())
        requests = mock_provider(handler=wait_for_release)
        async with REAL_ASYNC_CLIENT(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            uploaded = await client.post("/api/upload", files={"file": ("paper.pdf", make_pdf())})
            document_id = uploaded.json()["document_id"]
            pending = asyncio.create_task(client.post(f"/api/documents/{document_id}/summary"))
            await asyncio.wait_for(started.wait(), timeout=2)
            try:
                if replace_document:
                    replacement = await client.post("/api/upload", files={"file": ("new.pdf", make_pdf(("New paper",)))})
                    replacement_id = replacement.json()["document_id"]
                else:
                    duplicate = await client.post(f"/api/documents/{document_id}/summary")
                    assert duplicate.status_code == 409
            finally:
                release.set()
            result = await pending
            if replace_document:
                assert result.status_code == 404
                assert list(documents) == [replacement_id]
                assert "summary" not in documents[replacement_id]
            else:
                assert result.status_code == 200
            assert len(requests) == 1
    asyncio.run(scenario())


def test_long_paper_is_rejected_without_sending_a_partial_paper(client, make_pdf, monkeypatch):
    document_id = upload(client, make_pdf)
    monkeypatch.setattr(summarization, "MAX_SUMMARY_INPUT_BYTES", 10)
    response = client.post(f"/api/documents/{document_id}/summary")
    assert response.status_code == 413
    assert "No text was sent" in response.json()["detail"]


def test_input_limit_counts_utf8_bytes_and_accepts_the_exact_limit(monkeypatch):
    pages = [{"page_number": 3, "text": "éé"}]
    expected = "Page 3\néé"
    monkeypatch.setattr(summarization, "MAX_SUMMARY_INPUT_BYTES", len(expected.encode("utf-8")))
    assert build_paper_text(pages) == expected
    monkeypatch.setattr(summarization, "MAX_SUMMARY_INPUT_BYTES", len(expected.encode("utf-8")) - 1)
    with pytest.raises(SummaryError) as caught:
        build_paper_text(pages)
    assert caught.value.status_code == 413


def test_empty_source_text_cannot_be_summarized():
    with pytest.raises(SummaryError) as caught:
        build_paper_text([{"page_number": 1, "text": "   "}])
    assert caught.value.status_code == 422
