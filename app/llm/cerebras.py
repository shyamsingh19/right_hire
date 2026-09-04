from __future__ import annotations

from app.config import settings
from app.llm._openai_compatible import OpenAICompatibleProvider, _RateLimiter


class CerebrasProvider(OpenAICompatibleProvider):
    """LLM provider backed by Cerebras' inference API (OpenAI-compatible)."""

    provider_name = "Cerebras"
    base_url = "https://api.cerebras.ai/v1"
    _rate_limiter = _RateLimiter()

    def __init__(self, model: str | None = None) -> None:
        super().__init__(
            model=model or settings.cerebras_model,
            api_key=settings.cerebras_api_key,
            requests_per_minute=settings.cerebras_requests_per_minute,
            max_retries=settings.cerebras_max_retries,
            retry_backoff_base=settings.cerebras_retry_backoff_base,
        )
