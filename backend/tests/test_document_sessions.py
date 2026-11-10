import asyncio
import json

import httpx
import pytest

from backend import document_sessions, main
from backend.document_sessions import DOCUMENT_UNAVAILABLE, SESSION_HEADER, documents


def upload(client, pdf, token=None):
    headers = {} if token is None else {SESSION_HEADER: token}
    return client.post("/api/upload", files={"file": ("paper.pdf", pdf)}, headers=headers)


def test_concurrent_browsers_keep_separate_summaries_and_answers(make_pdf, mock_gemini):
    async def answer_provider(request):
        body = json.loads(request.content)
        text = body["contents"][0]["parts"][0]["text"]
        if text.startswith("{"):
            passage = json.loads(text)["passages"][0]
            answer = {
                "answer": passage["text"] + f" [Page {passage['page_number']}]",
                "cited_chunk_ids": [passage["chunk_id"]],
                "insufficient_evidence": False,
            }
        else:
            result = "The study recorded 20 samples." if "20 samples" in text else "The study recorded 80 samples."
            keys = body["generationConfig"]["responseJsonSchema"]["required"]
            answer = dict.fromkeys(keys, result)
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]},
        }]})

    calls = mock_gemini(handler=answer_provider)

    async def exercise():
        transport = httpx.ASGITransport(app=main.app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test") as first,
            httpx.AsyncClient(transport=transport, base_url="http://test") as second,
        ):
            papers = await asyncio.gather(*[
                browser.post("/api/upload", files={
                    "file": ("paper.pdf", make_pdf((f"The sample count recorded was {number} samples.",))),
                })
                for browser, number in ((first, 20), (second, 80))
            ])
            assert [paper.status_code for paper in papers] == [201, 201]
            one, two = [paper.json() for paper in papers]
            assert one["session_id"] != two["session_id"]
            first.headers[SESSION_HEADER] = one["session_id"]
            second.headers[SESSION_HEADER] = two["session_id"]

            for operation, options in (
                ("summary", {}), ("chat", {"json": {"question": "What sample count was recorded?"}}),
            ):
                foreign = await first.post(f"/api/documents/{two['document_id']}/{operation}", **options)
                assert foreign.status_code == 404
                assert foreign.json() == {"detail": DOCUMENT_UNAVAILABLE}

            async def read(browser, paper, number):
                path = f"/api/documents/{paper['document_id']}"
                summary = await browser.post(f"{path}/summary")
                chat = await browser.post(f"{path}/chat", json={"question": "What sample count was recorded?"})
                assert summary.status_code == chat.status_code == 200
                assert summary.headers["cache-control"] == chat.headers["cache-control"] == "no-store"
                assert f"{number} samples" in summary.json()["summary"]["key_results"]
                assert f"{number} samples" in chat.json()["answer"]
                assert chat.json()["sources"][0]["page_number"] == 1
                assert f"{number} samples" in chat.json()["evidence"][0]["excerpt"]

            await asyncio.gather(read(first, one, 20), read(second, two, 80))
            assert len(calls) == 4

    asyncio.run(exercise())


def test_replacing_one_session_keeps_other_document_and_rejects_missing_token(client, make_pdf):
    first = upload(client, make_pdf()).json()
    # This fixture remembers the last successful token. Explicitly remove it for a second browser.
    del client.headers[SESSION_HEADER]
    second = upload(client, make_pdf(("Other browser paper",))).json()
    replacement = upload(client, make_pdf(("Replacement paper",)), first["session_id"]).json()
    assert replacement["session_id"] == first["session_id"]
    assert set(documents) == {second["document_id"], replacement["document_id"]}

    del client.headers[SESSION_HEADER]
    response = client.post(f"/api/documents/{second['document_id']}/summary")
    assert response.status_code == 404
    assert response.json() == {"detail": DOCUMENT_UNAVAILABLE}
    response = upload(client, make_pdf(), "not-a-valid-session")
    assert response.status_code == 400
    assert "not-a-valid-session" not in response.text


def test_expiry_prunes_memory_and_reupload_issues_fresh_token(client, make_pdf, monkeypatch):
    now = 0
    monkeypatch.setattr(document_sessions, "monotonic", lambda: now)
    old = upload(client, make_pdf()).json()
    now += document_sessions.DOCUMENT_TTL_SECONDS
    expired = client.post(f"/api/documents/{old['document_id']}/summary")
    assert expired.status_code == 404
    assert expired.json() == {"detail": DOCUMENT_UNAVAILABLE}
    assert documents == {}
    fresh = upload(client, make_pdf(), old["session_id"]).json()
    assert fresh["session_id"] != old["session_id"]
    assert list(documents) == [fresh["document_id"]]


@pytest.mark.parametrize("limit, value", [("MAX_DOCUMENTS", 1), ("MAX_STORED_CHARACTERS", 30)])
def test_capacity_rejects_new_session_without_evicting_existing_one(client, make_pdf, monkeypatch, limit, value):
    monkeypatch.setattr(document_sessions, limit, value)
    first = upload(client, make_pdf()).json()
    del client.headers[SESSION_HEADER]
    rejected = upload(client, make_pdf())
    assert rejected.status_code == 503
    assert list(documents) == [first["document_id"]]
    replacement = upload(client, make_pdf(), first["session_id"])
    assert replacement.status_code == 201
    assert replacement.json()["session_id"] == first["session_id"]


def test_ai_concurrency_limit_releases_slot_after_completion(make_pdf, mock_gemini, monkeypatch):
    monkeypatch.setattr(main, "MAX_ACTIVE_AI_REQUESTS", 1)

    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()

        async def provider(request):
            started.set()
            await release.wait()
            schema = json.loads(request.content)["generationConfig"]["responseJsonSchema"]
            summary = dict.fromkeys(schema["required"], "Summary of the test paper.")
            return httpx.Response(200, json={"candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": json.dumps(summary)}]},
            }]})

        calls = mock_gemini(handler=provider)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            upload = await client.post("/api/upload", files={"file": ("paper.pdf", make_pdf())})
            paper = upload.json()
            client.headers[SESSION_HEADER] = paper["session_id"]
            endpoint = f"/api/documents/{paper['document_id']}/summary"
            pending = asyncio.create_task(client.post(endpoint))
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                busy = await client.post(endpoint)
                assert busy.status_code == 503
                assert busy.headers["retry-after"] == "2"
                assert len(calls) == 1
            finally:
                release.set()
                completed = await pending
            assert completed.status_code == 200
            assert (await client.post(endpoint)).status_code == 200
            assert len(calls) == 1

    asyncio.run(exercise())
