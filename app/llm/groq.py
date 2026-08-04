from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from app.config import settings
from app.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# Groq's OpenAI-compatible base URL
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(LLMProvider):
    """LLM provider backed by Groq's inference API (OpenAI-compatible)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.cascade_model or "llama3-8b-8192"
        self.api_key = settings.groq_api_key
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not set in environment")

    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Call Groq via instructor with structured output."""
        try:
            import instructor
            from openai import OpenAI

            client = instructor.from_openai(
                OpenAI(
                    api_key=self.api_key,
                    base_url=_GROQ_BASE_URL,
                ),
                mode=instructor.Mode.JSON,
            )
            return client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                response_model=schema,
                messages=[{"role": "user", "content": prompt}],
            )
        except ImportError:
            # Fallback: raw httpx call if instructor/openai not available
            import httpx

            schema_hint = json.dumps(schema.model_json_schema(), indent=2)
            full_prompt = (
                f"{prompt}\n\nRespond ONLY with valid JSON matching:\n{schema_hint}"
            )
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": full_prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{_GROQ_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return schema.model_validate(json.loads(content))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Groq does not provide an embedding API; callers must fall back to local."""
        raise NotImplementedError(
            "GroqProvider does not support embeddings. "
            "Use LocalProvider or OpenAIProvider for embed()."
        )
