from __future__ import annotations

from app.config import settings
from app.llm._openai_compatible import OpenAICompatibleProvider, _RateLimiter


class GroqProvider(OpenAICompatibleProvider):
    """LLM provider backed by Groq's inference API (OpenAI-compatible)."""

    provider_name = "Groq"
    base_url = "https://api.groq.com/openai/v1"
    _rate_limiter = _RateLimiter()

    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            model=model or settings.cascade_model,
            api_key=settings.groq_api_key,
            requests_per_minute=settings.groq_requests_per_minute,
            max_retries=settings.groq_max_retries,
            retry_backoff_base=settings.groq_retry_backoff_base,
        )

    def _extra_create_kwargs(self) -> dict:
        # gpt-oss models are reasoning models — without capping effort they can burn the
        # whole max_tokens budget on hidden reasoning before emitting any JSON, causing
        # empty completions (400 json_validate_failed).
        if "gpt-oss" in self.model:
            return {"reasoning_effort": "low"}
        return {}
