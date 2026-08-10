from __future__ import annotations

import time
import json
import logging

import httpx
from pydantic import BaseModel

from app.config import settings
from app.llm.base import LLMProvider, LLMUnavailableError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5  # seconds
_HEALTH_TIMEOUT = 5.0  # health probes must stay fast — /health is polled by load balancers


class LocalProvider(LLMProvider):
    """LLM provider that calls a local Ollama instance."""

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_url).rstrip("/")
        self.model = model or settings.judge_model

    # ── health_check ─────────────────────────────────────────────────────────

    def health_check(self) -> None:
        """Probe Ollama's /api/tags — cheap, and confirms JUDGE_MODEL is actually pulled."""
        with httpx.Client(timeout=_HEALTH_TIMEOUT) as client:
            resp = client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            available = {m.get("name", "") for m in resp.json().get("models", [])}
        # Ollama reports "qwen2.5:7b"; a bare "qwen2.5" in config should still match.
        if available and not any(
            name.split(":")[0] == self.model.split(":")[0] for name in available
        ):
            raise RuntimeError(
                f"Ollama is reachable but JUDGE_MODEL={self.model!r} is not pulled "
                f"(available: {sorted(available) or 'none'})"
            )

    # ── complete_json ────────────────────────────────────────────────────────

    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Call Ollama /api/chat with JSON format enforcement and retry."""
        system_msg = (
            "You are a precise data-extraction assistant. "
            "Respond ONLY with valid JSON that matches the requested schema. "
            "No markdown fences, no extra commentary."
        )
        schema_hint = json.dumps(schema.model_json_schema(), indent=2)
        full_prompt = (
            f"{prompt}\n\nYour response MUST be valid JSON matching this schema:\n{schema_hint}"
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": full_prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": max(max_tokens, 1024),  # never truncate JSON mid-string
                "temperature": 0.0,
            },
            "format": "json",
        }

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(f"{self.base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["message"]["content"]
                    parsed = json.loads(content)
                    return schema.model_validate(parsed)
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                last_exc = exc
                logger.warning(
                    "LocalProvider.complete_json attempt %d/%d failed: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE**attempt)

        # Name the underlying cause in the message itself, not just the __cause__ chain:
        # workers persist str(exc), so a bare "failed after N attempts" reaches the operator
        # with the actual reason (timeout? bad JSON? model unloaded?) already discarded.
        raise LLMUnavailableError(
            f"LocalProvider.complete_json failed after {_MAX_RETRIES} attempts "
            f"[{self.model} @ {self.base_url}] — {type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    # ── embed ────────────────────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama /api/embeddings for each text and return vectors."""
        embed_model = settings.embed_model
        results: list[list[float]] = []

        with httpx.Client(timeout=60.0) as client:
            for text in texts:
                last_exc = None
                for attempt in range(1, _MAX_RETRIES + 1):
                    try:
                        resp = client.post(
                            f"{self.base_url}/api/embeddings",
                            json={"model": embed_model, "prompt": text},
                        )
                        resp.raise_for_status()
                        vec = resp.json()["embedding"]
                        results.append(vec)
                        break
                    except (httpx.HTTPError, KeyError) as exc:
                        last_exc = exc
                        logger.warning(
                            "LocalProvider.embed attempt %d/%d failed: %s",
                            attempt,
                            _MAX_RETRIES,
                            exc,
                        )
                        if attempt < _MAX_RETRIES:
                            time.sleep(_BACKOFF_BASE**attempt)
                else:
                    raise LLMUnavailableError(
                        f"LocalProvider.embed failed after {_MAX_RETRIES} attempts "
                        f"[{embed_model} @ {self.base_url}] — "
                        f"{type(last_exc).__name__}: {last_exc}"
                    ) from last_exc

        return results
