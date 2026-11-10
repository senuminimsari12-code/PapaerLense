"""Try each configured AI provider in turn and keep the first valid answer.

This file answers five questions. They are worth reading in order, because the whole
provider system is just these five ideas:

1. Which provider goes first?
   PROVIDERS below is a fixed list: Gemini, then Groq, then OpenRouter.

2. Which providers are actually usable?
   find_configured_providers() keeps only the ones that have an API key in the
   environment. A provider with no key is skipped, never called.

3. How do we know a provider failed?
   Every adapter raises a ProviderError (bad key, rate limit, timeout, unreadable
   reply). Validation failures raise one too. Either way, we move to the next provider.

4. How long may each provider take?
   There is ONE deadline for the whole request. Early attempts have capped shares,
   leaving more time for a slower backup. The last provider gets what remains.

5. What if every provider fails?
   generate_with_failover raises one safe ProviderError. The user's PDF is untouched
   and they can retry.

Two rules this file must never break:
- One attempt per provider. No retry loops, so we never pay twice for one question.
- One provider at a time, in order. We never ask them all at once.
"""

import asyncio
import logging
import os
import re
from collections.abc import Callable
from typing import NamedTuple

from backend import gemini_client
from backend.ai_errors import ProviderError
from backend.openai_compatible_client import request_completion

# The priority order. Gemini is the primary provider; the other two are backups used
# only when the one before them fails. Each entry is (provider name, default model).
# A GEMINI_MODEL / GROQ_MODEL / OPENROUTER_MODEL environment variable overrides the default.
PROVIDERS = (
    ("gemini", gemini_client.DEFAULT_MODEL),
    ("groq", "openai/gpt-oss-120b"),
    ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
)

# The placeholder shipped in .env.example. Treated as "no key set" so that copying the
# example file without editing it does not look like a configured provider.
PLACEHOLDER_KEY = "your_gemini_api_key_here"

# Caps apply only when another configured provider is still available.
EARLY_ATTEMPT_CAPS = {
    "summary": {"gemini": 20, "groq": 15},
    "qa": {"gemini": 18, "groq": 12},
}
MINIMUM_START_SECONDS = 2

# A model name may only contain these characters. Anything else is a configuration
# mistake, and we refuse it rather than sending it to a provider or writing it to a log.
SAFE_MODEL_NAME = re.compile(r"[a-zA-Z0-9._:/-]{1,200}")

# Log under uvicorn's logger so provider activity appears in the normal server output.
logger = logging.getLogger("uvicorn.error").getChild("paperlens.ai")


class ConfiguredProvider(NamedTuple):
    """One provider we are allowed to call, with the key and model it should use."""

    name: str
    api_key: str
    model: str


def find_configured_providers(request_type: str) -> list[ConfiguredProvider]:
    """Return the providers that have an API key, keeping the PROVIDERS priority order.

    request_type is only used for the log line ("summary" or "qa"). Providers without a
    key are logged as skipped, which makes a missing key obvious in the server output
    instead of looking like a silent failure.
    """
    configured_providers = []

    for provider_name, default_model in PROVIDERS:
        api_key = os.getenv(f"{provider_name.upper()}_API_KEY", "").strip()
        chosen_model = os.getenv(f"{provider_name.upper()}_MODEL", "").strip()
        if not chosen_model:
            chosen_model = default_model

        if api_key and api_key != PLACEHOLDER_KEY:
            configured_providers.append(
                ConfiguredProvider(name=provider_name, api_key=api_key, model=chosen_model)
            )
        else:
            logger.info(
                "AI provider=%s request=%s status=skipped category=missing_key",
                provider_name, request_type,
            )

    return configured_providers


def model_name_is_safe(model: str, configured_providers: list[ConfiguredProvider]) -> bool:
    """Check that a model name is a plain name and not an API key pasted by mistake.

    Why bother? Model names get written to log files. If someone accidentally put their
    API key in GROQ_MODEL instead of GROQ_API_KEY, logging the "model" would leak the
    key. So we reject any model name that matches, or contains, a configured key.
    """
    if not SAFE_MODEL_NAME.fullmatch(model):
        return False

    for other_provider in configured_providers:
        secret = other_provider.api_key
        if model == secret:
            return False
        # Short strings could match by coincidence, so only treat a real-length key as
        # a secret that must not appear inside a model name.
        if len(secret) >= 12 and secret in model:
            return False

    return True


async def ask_one_provider(provider: ConfiguredProvider, instructions: str, contents: str,
                           schema: dict, max_output_tokens: int, time_budget: float,
                           gemini_http_timeout_ms: int | None) -> tuple[str, str]:
    """Send the request to one provider and return (generated text, model actually used).

    Gemini uses the official Google SDK, so it has its own adapter. Groq and OpenRouter
    share the OpenAI-style adapter. Gemini also reports back which model it used, which
    is why this returns the model name rather than assuming it.
    """
    if provider.name == "gemini":
        response, model_used = await gemini_client.request_gemini(
            instructions, contents, schema,
            max_output_tokens=max_output_tokens,
            timeout_seconds=time_budget,
            http_timeout_ms=gemini_http_timeout_ms,
        )
        return gemini_client.response_text(response), model_used

    generated_text = await request_completion(
        provider.name, provider.api_key, provider.model,
        instructions, contents, schema, max_output_tokens,
    )
    return generated_text, provider.model


async def generate_with_failover(
    request_type: str,
    instructions: str,
    contents: str,
    schema: dict,
    validate: Callable[[str], object],
    *,
    max_output_tokens: int = 6_000,
    timeout_seconds: float = 90,
    gemini_http_timeout_ms: int | None = 60_000,
) -> tuple[object, str]:
    """Ask each configured provider once, and return the first answer that validates.

    Inputs:
      request_type  - "summary" or "qa". Used only in log lines.
      instructions  - the system prompt telling the model what the rules are.
      contents      - the data: the paper text, or the question plus retrieved passages.
      schema        - the JSON shape we require back.
      validate      - a function that turns the provider's text into a checked object,
                      or raises ProviderError if the text is unacceptable. The SAME
                      validate function is used for every provider, so a backup can
                      never return something the primary would have been refused for.

    Returns (validated result, model name that produced it).
    Raises ProviderError if nothing is configured, or if every provider failed.
    """
    configured_providers = find_configured_providers(request_type)

    if not configured_providers:
        raise ProviderError(
            "AI features are not configured. Set GEMINI_API_KEY, GROQ_API_KEY, or "
            "OPENROUTER_API_KEY in the backend environment and restart the backend.",
            503, category="missing_key",
        )

    # One shared deadline for the whole request. loop.time() is a steady clock, so it
    # is not affected by the computer's clock changing.
    event_loop = asyncio.get_running_loop()
    deadline = event_loop.time() + timeout_seconds

    # If we somehow run out of time before trying anything, this is what we report.
    last_error = ProviderError(
        "The AI request timed out. Please try again.", 504, category="timeout"
    )
    last_non_size_error = last_error
    size_rejections = 0
    input_bytes = len(contents.encode("utf-8"))

    for position, provider in enumerate(configured_providers):
        started_at = event_loop.time()
        time_remaining = deadline - started_at
        # Keep the floor proportional for short caller-supplied deadlines.
        if time_remaining <= 0 or (
            position > 0 and time_remaining < min(MINIMUM_START_SECONDS, timeout_seconds / 10)
        ):
            break

        providers_left = len(configured_providers) - position
        time_budget = time_remaining / providers_left
        if providers_left > 1:
            cap = EARLY_ATTEMPT_CAPS.get(request_type, {}).get(provider.name, time_budget)
            time_budget = min(time_budget, cap)

        model_is_safe = model_name_is_safe(provider.model, configured_providers)
        model_for_logging = provider.model if model_is_safe else "[redacted]"
        model_used = provider.model

        # Tracks how far we got, so the log says whether the provider failed to answer
        # ("request") or answered with something unacceptable ("validation").
        phase = "request"

        try:
            if not model_is_safe:
                raise ProviderError(
                    "The AI provider model configuration is invalid.", 503,
                    category="configuration",
                )

            # This timeout covers the network call AND validation together, which is
            # why the adapters below do not set their own competing timeouts.
            async with asyncio.timeout_at(started_at + time_budget):
                generated_text, model_used = await ask_one_provider(
                    provider, instructions, contents, schema,
                    max_output_tokens, time_budget, gemini_http_timeout_ms,
                )
                phase = "validation"
                validated_result = validate(generated_text)
                if event_loop.time() >= started_at + time_budget:
                    raise TimeoutError

        except TimeoutError:
            last_error = ProviderError(
                "The AI request timed out. Please try again.", 504, category="timeout"
            )
        except ProviderError as error:
            last_error = error
        else:
            # Success. Stop here: do not contact any remaining provider.
            logger.info(
                "AI provider=%s model=%s request=%s status=success duration_ms=%d fallback=%s "
                "budget_ms=%d input_bytes=%d",
                provider.name, model_for_logging, request_type,
                (event_loop.time() - started_at) * 1000, provider.name != "gemini",
                time_budget * 1000, input_bytes,
            )
            return validated_result, model_used

        # Only reached when this provider failed. Log why, then try the next one.
        if last_error.category == "payload_too_large":
            size_rejections += 1
        else:
            last_non_size_error = last_error
        logger.warning(
            "AI provider=%s model=%s request=%s status=failed category=%s "
            "upstream_code=%s phase=%s duration_ms=%d fallback=%s budget_ms=%d input_bytes=%d "
            "validation_check=%s",
            provider.name, model_for_logging, request_type,
            last_error.category, last_error.upstream_status or (200 if phase == "validation" else None), phase,
            (event_loop.time() - started_at) * 1000, provider.name != "gemini",
            time_budget * 1000, input_bytes, last_error.validation_check,
        )

    # No provider returned a valid result before the deadline.
    if len(configured_providers) == 1:
        # With a single provider there is no "they all failed" story to tell, so the
        # user gets that provider's specific reason instead of a vague summary.
        raise last_error

    if size_rejections == len(configured_providers):
        # The paper was rejected for its size rather than for a fault, so say so. A
        # vague "try again later" would be wrong here: retrying the same paper cannot
        # help. PaperLense still never shortens the paper on its own.
        raise ProviderError(
            "This paper is larger than the configured AI providers' request size limits. "
            "Try a shorter paper or a clearly labeled excerpt. "
            "Your PDF is still available and was not shortened.",
            413, category="payload_too_large",
        )

    raise ProviderError(
        "The configured AI providers could not complete this request. "
        "Please try again later. Your PDF is still available.",
        last_non_size_error.status_code,
    )
