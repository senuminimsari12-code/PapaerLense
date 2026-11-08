"""Send one request to Groq or OpenRouter and return the text they generated.

Why do two providers share one file?
Groq and OpenRouter both copy OpenAI's "chat completions" API. The URL differs and a
few options differ, but the request body and the response shape are the same. So one
adapter can talk to both, and we only need to branch in the small places where they
actually disagree.

Gemini is different enough that it has its own file, backend/gemini_client.py.

Reading order for this file:
1. GROQ_URL / OPENROUTER_URL      - where each provider lives.
2. build_request_payload          - the JSON body we send.
3. read_generated_text            - pull the text out of the JSON we get back.
4. request_completion             - the function the failover loop actually calls.
"""

import json
import logging
import re

import httpx

from backend.ai_errors import ProviderError
from backend.http_error_messages import provider_error_for_status

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# These two Groq models accept a "reasoning_effort" option. Keeping it low makes
# replies faster and cheaper, which matters because Groq is only a backup provider.
GROQ_MODELS_WITH_REASONING_EFFORT = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}

logger = logging.getLogger(__name__)


def build_request_payload(provider: str, model: str, instructions: str, contents: str,
                          schema: dict, max_output_tokens: int) -> tuple[str, dict]:
    """Build the URL and JSON body for one provider.

    The important difference between the two providers is how we ask for JSON:

    - Groq supports a real "json_schema" response format, so we hand it the schema
      and the provider itself guarantees the shape.
    - OpenRouter's free models do not reliably support that, so instead we paste the
      schema into the instructions and ask for a bare JSON object in words.

    Returns a (url, payload) pair so the caller does not have to know these details.
    """
    payload = {"model": model}

    if provider == "groq":
        url = GROQ_URL
        payload["max_completion_tokens"] = max_output_tokens
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "paperlens_output", "strict": True, "schema": schema},
        }
        if model in GROQ_MODELS_WITH_REASONING_EFFORT:
            payload["reasoning_effort"] = "low"
    else:
        url = OPENROUTER_URL
        payload["max_tokens"] = max_output_tokens
        instructions = instructions + (
            "\nReturn only one JSON object matching this schema, without Markdown.\n"
            + json.dumps(schema, separators=(",", ":"))
        )

    # Both providers take the same two-message conversation: the rules, then the data.
    payload["messages"] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": contents},
    ]
    return url, payload


def read_generated_text(response: httpx.Response) -> str:
    """Read the generated text out of a successful provider response.

    This is deliberately strict. We only accept a reply that the provider says it
    finished writing, because a half-written answer would fail validation later with a
    confusing error. Anything unexpected becomes one safe ProviderError, so a provider's
    raw error text can never reach the user or the logs.
    """
    try:
        result = response.json()

        # OpenRouter sometimes reports an upstream failure inside an HTTP 200 response,
        # so a 200 status alone is not proof that the request worked.
        if "error" in result:
            error_code = result["error"].get("code")
            if type(error_code) is int and 400 <= error_code <= 599:
                raise provider_error_for_status(error_code)
            raise ValueError("Unrecognized provider error")

        # The comma unpacks a list of exactly one choice. More than one is unexpected.
        choice, = result["choices"]
        generated_text = choice["message"]["content"]

        if choice["finish_reason"] != "stop":
            raise ValueError("Provider stopped early")
        if not isinstance(generated_text, str) or not generated_text.strip():
            raise ValueError("Provider returned no text")

        return generated_text
    except ProviderError:
        raise
    except (KeyError, IndexError, AttributeError, TypeError, ValueError):
        raise ProviderError(
            "The AI provider returned an unreadable response.",
            upstream_status=response.status_code,
        ) from None


def strip_markdown_code_fence(text: str) -> str:
    """Remove a ```json ... ``` wrapper if the model added one.

    We asked OpenRouter for bare JSON in words rather than enforcing a schema, so it
    sometimes wraps the JSON in a Markdown code fence. Removing the fence here means
    the JSON parser downstream does not have to care.
    """
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced[1]
    return text


async def request_completion(provider: str, api_key: str, model: str, instructions: str,
                             contents: str, schema: dict, max_output_tokens: int) -> str:
    """Make one request to Groq or OpenRouter and return the generated text.

    This function never retries. The failover loop in backend/ai_providers.py decides
    whether to move on to the next provider, so retrying here would cause duplicate
    requests and double-charging.
    """
    url, payload = build_request_payload(
        provider, model, instructions, contents, schema, max_output_tokens
    )
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        # timeout=None looks wrong but is correct here: the failover loop wraps this
        # call in asyncio.timeout() so that one shared deadline covers connecting,
        # waiting for the reply and validating it. Two competing timeouts would make
        # the time budget impossible to reason about.
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException:
        # 408 is the "request timed out" status, which gives the user a clear message.
        raise provider_error_for_status(408) from None
    except httpx.RequestError:
        raise ProviderError(
            "Could not reach the AI provider. Please try again in a moment.",
            503, category="connection",
        ) from None

    if response.is_error:
        raise provider_error_for_status(response.status_code)

    generated_text = read_generated_text(response)

    if provider == "openrouter":
        generated_text = strip_markdown_code_fence(generated_text)

    return generated_text
