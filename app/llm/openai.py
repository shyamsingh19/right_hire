from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import settings
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"


class OpenAIProvider(LLMProvider):
    """LLM provider backed by OpenAI."""

    def __init__(self, model: str | None = None) -> None:
        import openai  # noqa: F401 — validate it's installed at construction time

        self.model = model or "gpt-4o-mini"
        self.api_key = settings.openai_api_key
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment")

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
        return client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            response_model=schema,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings using OpenAI text-embedding-3-small."""
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.embeddings.create(
            model=_EMBED_MODEL,
            input=texts,
        )
        # Sort by index to guarantee order matches input
        items = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in items]
