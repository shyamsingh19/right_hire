from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMProvider(ABC):
    """Abstract base for all LLM backends."""

    @abstractmethod
    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Send *prompt* to the LLM and return a validated *schema* instance."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return dense embeddings for each string in *texts*."""
        ...
