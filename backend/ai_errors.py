"""The one error type used for every AI provider problem.

This lives in its own small file so that the provider adapters, the validators and the
API endpoints can all share it without importing each other in a circle.

Other files import it under a clearer local name:
    backend/summarization.py  ->  SummaryError
    backend/gemini_client.py  ->  GeminiError
They are the same class; only the name in that file differs, to make the code read
naturally where it is used.
"""


class ProviderError(ValueError):
    """Something went wrong with an AI provider, described safely.

    The whole point of this class is that its message is always text WE wrote, never
    text a provider sent us. A provider's own error body can contain our API key or
    parts of the user's paper, so it is discarded and replaced with one of our messages.

    Fields:
      message          - safe text the user may be shown. Pass it as the first argument.
      status_code      - the HTTP status PaperLense returns to the frontend (e.g. 503).
      category         - a short label used only in log lines, so a developer can see
                         the kind of failure at a glance: "timeout", "rate_limit",
                         "credentials", "connection", "upstream", "configuration",
                         "missing_key" or the default "invalid_output".
      upstream_status  - the provider's own HTTP status, kept for diagnosis in logs.
                         None when the failure happened before any reply arrived.
    """

    def __init__(self, message: str, status_code: int = 502, *,
                 category: str = "invalid_output", upstream_status: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.upstream_status = upstream_status
