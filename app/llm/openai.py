from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import settings
from app.llm.base import LLMProvider, LLMUnavailableError

logger = logging.getLogger(__name__)

_HEALTH_TIMEOUT = 5.0


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI."""

    def __init__(self, model: str | None = None) -> None:
        import openai  # noqa: F401 — validate it's installed at construction time

        self.model = model or settings.openai_model
        self.api_key = settings.openai_api_key
        if not self.api_key:
            raise LLMUnavailableError("OPENAI_API_KEY is not set — LLM_BACKEND=openai requires it")

    def health_check(self) -> None:
        """Probe OpenAI's /models — validates both reachability and the API key."""
        import httpx

        with httpx.Client(timeout=_HEALTH_TIMEOUT) as client:
            resp = client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()

    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Use instructor + OpenAI to return a structured Pydantic model."""
        import instructor
        from openai import OpenAI

        client = instructor.from_openai(
            OpenAI(api_key=self.api_key),
            mode=instructor.Mode.JSON,
        )
        try:
            return client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                response_model=schema,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
        except Exception as exc:
            if type(exc).__module__.startswith("openai"):
                raise LLMUnavailableError(f"OpenAIProvider.complete_json failed: {exc}") from exc
            raise

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings using OpenAI text-embedding-3-small."""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        try:
            response = client.embeddings.create(
                model=settings.openai_embed_model,
                input=texts,
            )
        except Exception as exc:
            if type(exc).__module__.startswith("openai"):
                raise LLMUnavailableError(f"OpenAIProvider.embed failed: {exc}") from exc
            raise
        # Sort by index to guarantee order matches input
        items = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in items]
