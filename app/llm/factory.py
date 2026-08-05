from __future__ import annotations

from app.config import settings
from app.llm.base import LLMProvider


def get_provider() -> LLMProvider:
    """Instantiate and return the configured LLM provider.

    Reads ``settings.llm_backend`` (env var ``LLM_BACKEND``).
    Valid values: ``local``, ``groq``, ``openai``.
    """
    backend = settings.llm_backend.lower().strip()

    if backend == "local":
        from app.llm.local import LocalProvider

        return LocalProvider()

    if backend == "groq":
        from app.llm.groq import GroqProvider

        return GroqProvider()

    if backend == "openai":
        from app.llm.openai import OpenAIProvider

        return OpenAIProvider()

    raise ValueError(f"Unknown LLM_BACKEND={backend!r}. Choose one of: local, groq, openai")
