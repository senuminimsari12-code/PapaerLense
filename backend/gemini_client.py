"""Send one request to Google Gemini, the primary AI provider.

Gemini has its own file because it uses Google's official SDK (`google-genai`) rather
than plain HTTP. Groq and OpenRouter share backend/openai_compatible_client.py instead.

Two functions matter here:
  request_gemini  - make one request and return the SDK's response object.
  response_text   - pull the generated text out of that response object, safely.

They are separate because the failover loop times the request and the validation
together, so it needs to call them as two steps.

A rule this file follows strictly: no automatic retries. The SDK would happily retry a
failed request, which would mean paying twice and waiting twice for a provider that is
already in trouble. retry_options below turns that off, and the failover loop in
backend/ai_providers.py decides whether to move on to the next provider instead.
"""

import asyncio
import logging
import os

import httpx
from google import genai
from google.genai import errors, types

# ProviderError under a clearer name for readers of this file.
from backend.ai_errors import ProviderError as GeminiError

GEMINI_API_URL = "https://generativelanguage.googleapis.com"

# Used when GEMINI_MODEL is not set in the environment.
DEFAULT_MODEL = "gemini-3.8-flash"

# The placeholder from .env.example, treated as "no key configured".
PLACEHOLDER_KEY = "your_gemini_api_key_here"

# Google status strings we are willing to write to a log. Anything outside this list is
# logged as "UNCLASSIFIED", because the status field is provider-controlled text and
# could otherwise put arbitrary content, or our own key, into the log file.
LOGGABLE_API_STATUSES = {
    "INVALID_ARGUMENT", "FAILED_PRECONDITION", "UNAUTHENTICATED", "PERMISSION_DENIED",
    "NOT_FOUND", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL",
}

logger = logging.getLogger(__name__)


def response_text(response: types.GenerateContentResponse) -> str:
    """Read the generated text out of a Gemini response.

    This is strict on purpose. Three things it insists on:

    1. Exactly one candidate. We asked for one answer, so more than one means something
       unexpected happened and we should not quietly pick the first.
    2. finish_reason must be STOP, meaning Gemini finished writing. A reply cut off by a
       length limit or a safety filter is incomplete and is rejected.
    3. "Thinking" parts are skipped. Gemini can return internal reasoning alongside the
       answer; that reasoning is not for the user and must never be shown or logged.

    Returns the generated text. Raises GeminiError for anything unusable.
    """
    try:
        if not isinstance(response, types.GenerateContentResponse):
            raise ValueError("Expected a Gemini SDK response")

        # No candidates usually means a safety filter blocked the request outright.
        if not response.candidates:
            raise GeminiError(
                "The AI provider could not answer this request. "
                "Try another question or document."
            )

        if len(response.candidates) != 1:
            raise ValueError("Expected one candidate")

        candidate = response.candidates[0]
        if candidate.finish_reason != types.FinishReason.STOP:
            raise GeminiError("The AI provider did not finish the response. Please try again.")

        # Long answers arrive split across several parts, so collect and join them.
        text_parts = []
        for part in candidate.content.parts:
            if part.thought:
                continue
            if not isinstance(part.text, str):
                raise ValueError("Expected text output")
            text_parts.append(part.text)

        generated_text = "".join(text_parts)
        if not generated_text.strip():
            raise ValueError("Empty output")

        return generated_text

    except GeminiError:
        # Already a safe, user-facing message.
        raise
    except (KeyError, TypeError, AttributeError, ValueError):
        # The response was shaped differently than the SDK's own type promises.
        raise GeminiError(
            "The AI provider returned an invalid or incomplete response. Please try again."
        ) from None


def read_api_key() -> str:
    """Read GEMINI_API_KEY from the environment, or explain how to set it.

    Raises GeminiError(503) when no usable key is configured. The message mentions
    VITE_ because putting the key in a VITE_ variable would bundle it into the
    frontend's JavaScript and publish it to every visitor.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if not api_key or api_key == PLACEHOLDER_KEY:
        raise GeminiError(
            "AI features are not configured. Set GEMINI_API_KEY in the backend's "
            "environment or the project's local .env file, then restart the backend. "
            "Never put the key in a VITE_ variable.", 503,
        )

    return api_key


def describe_api_failure(error: errors.APIError) -> GeminiError:
    """Turn a Gemini API error into a safe message, and log it without leaking anything.

    Gemini's own error body can contain our API key or text from the user's paper, so we
    log only the HTTP code and an allowlisted status string, and we return a message we
    wrote ourselves.
    """
    status = getattr(error, "status", None)
    if not isinstance(status, str) or status not in LOGGABLE_API_STATUSES:
        status = "UNCLASSIFIED"

    logger.warning("Gemini API failed (HTTP %s; status %s).", error.code, status)

    if error.code in (401, 403):
        return GeminiError(
            "The AI provider rejected the backend credentials or access. "
            "Check GEMINI_API_KEY and project/model access.",
            503, category="credentials", upstream_status=error.code,
        )

    if error.code == 429:
        return GeminiError(
            "The AI provider's rate or usage limit was reached. "
            "Check your quota or try again later.",
            429, category="rate_limit", upstream_status=error.code,
        )

    if error.code in (408, 504):
        return GeminiError(
            "The AI request timed out. Please try again.",
            504, category="timeout", upstream_status=error.code,
        )

    if error.code == 413:
        # The paper was too big for Gemini's request limit. Kept separate from the
        # configuration case below so a backup provider with a larger limit is still
        # tried, and so the message does not wrongly blame the key or the model name.
        return GeminiError(
            "This paper is larger than that AI provider's request size limit.",
            413, category="payload_too_large", upstream_status=error.code,
        )

    if error.code >= 500:
        return GeminiError(
            "The AI provider is temporarily unavailable. Please try again later.",
            503, category="upstream", upstream_status=error.code,
        )

    # Usually 400 or 404: a bad model name, or a project without access to that model.
    return GeminiError(
        "The AI provider rejected the request. "
        "Check GEMINI_API_KEY, GEMINI_MODEL, and project/model access.",
        category="configuration", upstream_status=error.code,
    )


def build_generation_config(instructions: str, schema: dict,
                            max_output_tokens: int) -> types.GenerateContentConfig:
    """Assemble the settings for one Gemini request.

    The important ones:
      system_instruction   - the rules, kept separate from the user's data.
      response_mime_type   - ask for JSON rather than prose.
      response_json_schema - the exact shape required, enforced by Gemini itself.
      thinking_config      - allow a little internal reasoning but do not return it.
      candidate_count=1    - one answer only; we have no use for alternatives.
    """
    return types.GenerateContentConfig(
        system_instruction=instructions,
        response_mime_type="application/json",
        response_json_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level="LOW", include_thoughts=False),
        candidate_count=1,
        max_output_tokens=max_output_tokens,
    )


async def request_gemini(instructions: str, contents: str, schema: dict,
                         max_output_tokens: int = 6_000, timeout_seconds: float = 90,
                         http_timeout_ms: int | None = 60_000):
    """Make exactly one Gemini request.

    Inputs:
      instructions     - the system prompt (the rules).
      contents         - the data: the paper text, or the question plus passages.
      schema           - the JSON shape required back.
      timeout_seconds  - overall deadline for this attempt, set by the failover loop.
      http_timeout_ms  - optional per-connection timeout, or None to rely only on the
                         overall deadline above.

    Returns (the SDK response, the model name used).
    Raises GeminiError for a missing key, a network problem, a timeout, or an API error.
    """
    api_key = read_api_key()

    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not model:
        model = DEFAULT_MODEL

    config = build_generation_config(instructions, schema, max_output_tokens)

    http_options = types.HttpOptions(
        base_url=GEMINI_API_URL,
        api_version="v1beta",
        timeout=http_timeout_ms,
        # A redirect could replay the API key header and document at another host.
        async_client_args={"follow_redirects": False},
        # attempts=1 means "try once, never retry". See this file's docstring.
        retry_options=types.HttpRetryOptions(attempts=1),
    )

    try:
        # Two nested `async with` blocks:
        #   asyncio.timeout - cancels everything inside if the deadline passes.
        #   genai.Client(...).aio - the async SDK client, closed automatically so no
        #                           connection is left open after the request.
        async with asyncio.timeout(timeout_seconds):
            client = genai.Client(api_key=api_key, enterprise=False, http_options=http_options)
            async with client.aio as async_client:
                response = await async_client.models.generate_content(
                    model=model, contents=contents, config=config
                )

    except (httpx.TimeoutException, TimeoutError) as error:
        # Logs the exception type only, never its message.
        logger.warning("Gemini transport/deadline failed (%s).", type(error).__name__)
        raise GeminiError(
            "The AI request timed out. Please try again.", 504, category="timeout"
        ) from None

    except httpx.RequestError:
        # Could not reach Google at all: DNS, TLS or no network.
        raise GeminiError(
            "Could not reach the AI provider. Please try again in a moment.",
            503, category="connection",
        ) from None

    except errors.APIError as error:
        # Google answered, but with an error. describe_api_failure does the logging.
        raise describe_api_failure(error) from None

    except (KeyError, TypeError, AttributeError, ValueError):
        raise GeminiError(
            "The AI provider returned an unreadable response. Please try again."
        ) from None

    return response, model
