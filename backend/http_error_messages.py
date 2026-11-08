"""Turn an AI provider's HTTP status code into a safe message for the user.

Why this file exists:
When a provider fails, its own error text can contain our API key, internal URLs, or
pieces of the user's paper. We must never show that text or write it to a log. So every
failure is translated here into a fixed message that we wrote ourselves, plus a short
"category" label used only for logging.

The returned ProviderError carries:
- message          - safe text the user may see.
- status_code      - the status PaperLense will return to the frontend.
- category         - a short label for the log line ("timeout", "rate_limit", ...).
- upstream_status  - the provider's original status, kept for diagnosis in logs.
"""

from backend.ai_errors import ProviderError


def provider_error_for_status(status: int) -> ProviderError:
    """Map one provider HTTP status to the error PaperLense should raise.

    Read this as a short list of rules, most specific first:

    401 / 403  -> our key was rejected. Not the user's fault, so report "unavailable".
    429        -> we hit a rate or quota limit. Passed through as 429 so the frontend
                  can tell the user to wait rather than suggesting a broken setup.
    408 / 504  -> the provider took too long.
    413        -> the paper was too big for THAT provider's request limit. Nothing is
                  wrong with our setup, and a provider with a bigger limit may still
                  succeed, so this must not be reported as a configuration problem.
    500+       -> the provider is broken right now; trying again later may work.
    anything else (usually 400 / 404) -> we sent something the provider would not
                  accept, such as an unknown model name.
    """
    if status in (401, 403):
        return ProviderError(
            "The AI provider rejected the backend credentials or access.",
            503, category="credentials", upstream_status=status,
        )

    if status == 429:
        return ProviderError(
            "The AI provider's rate or usage limit was reached. Please try again later.",
            429, category="rate_limit", upstream_status=status,
        )

    if status in (408, 504):
        return ProviderError(
            "The AI request timed out. Please try again.",
            504, category="timeout", upstream_status=status,
        )

    if status == 413:
        # One provider's request-size limit, not a problem with PaperLense. Groq's free
        # tier rejects a full-length paper this way while OpenRouter accepts the same
        # paper, so the failover loop should simply move on to the next provider.
        return ProviderError(
            "This paper is larger than that AI provider's request size limit.",
            413, category="payload_too_large", upstream_status=status,
        )

    if status >= 500:
        return ProviderError(
            "The AI provider is temporarily unavailable. Please try again later.",
            503, category="upstream", upstream_status=status,
        )

    return ProviderError(
        "The AI provider rejected the configured model or request.",
        502, category="configuration", upstream_status=status,
    )
