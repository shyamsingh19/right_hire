from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMUnavailableError(RuntimeError):
    """Raised when the configured LLM backend can't be reached or misconfigured.

    Caught at the API boundary (app/main.py) and turned into a 503 with a
    user-friendly message instead of a raw 500 stack trace.
    """


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

    def health_check(self) -> None:
        """Cheap reachability probe — raise if the backend is unreachable.

        Called by ``GET /health`` so a dead LLM connection surfaces before a
        customer's batch silently fails. Must not consume tokens or bill: probe a
        list-models style endpoint, never a completion. Not abstract — the default
        no-op keeps this optional for providers with no cheap probe.
        """
        return None
