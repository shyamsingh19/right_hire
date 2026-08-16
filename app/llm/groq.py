from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque

from pydantic import BaseModel

from app.config import settings
from app.llm.base import LLMProvider, LLMUnavailableError

logger = logging.getLogger(__name__)

# Groq's OpenAI-compatible base URL
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_HEALTH_TIMEOUT = 5.0


class _RateLimiter:
    """Sliding-window throttle so we stay under Groq's requests-per-minute cap instead of
    finding out via 429s. Shared across all calls in this process (one RQ worker == one
    process handling candidates one at a time, so a process-local window is sufficient)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def wait(self) -> None:
        limit = max(settings.groq_requests_per_minute, 1)
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > 60.0:
                self._calls.popleft()
            if len(self._calls) >= limit:
                sleep_for = 60.0 - (now - self._calls[0])
                if sleep_for > 0:
                    logger.info(
                        "GroqProvider throttling — at %d/%d requests this minute, waiting %.1fs",
                        len(self._calls),
                        limit,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                now = time.monotonic()
                while self._calls and now - self._calls[0] > 60.0:
                    self._calls.popleft()
            self._calls.append(time.monotonic())


_rate_limiter = _RateLimiter()


def _retry_after_seconds(exc: Exception) -> float | None:
    """Best-effort extraction of a Retry-After header from an openai/httpx error."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class GroqProvider(LLMProvider):
    """LLM provider backed by Groq's inference API (OpenAI-compatible)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.cascade_model
        self.api_key = settings.groq_api_key
        if not self.api_key:
            raise LLMUnavailableError("GROQ_API_KEY is not set — LLM_BACKEND=groq requires it")

    def health_check(self) -> None:
        """Probe Groq's /models — validates both reachability and the API key."""
        import httpx

        with httpx.Client(timeout=_HEALTH_TIMEOUT) as client:
            resp = client.get(
                f"{_GROQ_BASE_URL}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()

    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Call Groq via instructor with structured output, throttled to stay under the
        configured requests-per-minute cap and retried with backoff on transient failure."""
        max_retries = max(settings.groq_max_retries, 1)
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            _rate_limiter.wait()
            try:
                return self._complete_json_once(prompt, schema, max_tokens)
            except LLMUnavailableError as exc:
                last_exc = exc
                logger.warning(
                    "GroqProvider.complete_json attempt %d/%d failed [model=%s]: %s",
                    attempt,
                    max_retries,
                    self.model,
                    exc,
                )
                if attempt < max_retries:
                    retry_after = _retry_after_seconds(exc.__cause__) if exc.__cause__ else None
                    delay = retry_after or settings.groq_retry_backoff_base**attempt
                    time.sleep(delay)

        raise LLMUnavailableError(
            f"GroqProvider.complete_json failed after {max_retries} attempts "
            f"[{self.model}] — {type(last_exc).__name__}: {last_exc}"
        ) from last_exc

    def _complete_json_once(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int,
    ) -> BaseModel:
        import httpx

        try:
            try:
                import instructor
                from openai import OpenAI

                client = instructor.from_openai(
                    OpenAI(
                        api_key=self.api_key,
                        base_url=_GROQ_BASE_URL,
                        timeout=60.0,
                    ),
                    mode=instructor.Mode.JSON,
                )
                result, completion = client.chat.completions.create_with_completion(
                    model=self.model,
                    max_tokens=max_tokens,
                    response_model=schema,
                    messages=[{"role": "user", "content": prompt}],
                )
                usage = completion.usage
                logger.info(
                    "GroqProvider.complete_json tokens — model=%s prompt=%d completion=%d total=%d",
                    self.model,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                )
                return result
            except ImportError:
                # Fallback: raw httpx call if instructor/openai not available
                schema_hint = json.dumps(schema.model_json_schema(), indent=2)
                full_prompt = f"{prompt}\n\nRespond ONLY with valid JSON matching:\n{schema_hint}"
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
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    logger.info(
                        "GroqProvider.complete_json tokens (raw) — model=%s prompt=%s "
                        "completion=%s total=%s",
                        self.model,
                        usage.get("prompt_tokens"),
                        usage.get("completion_tokens"),
                        usage.get("total_tokens"),
                    )
                    return schema.model_validate(json.loads(content))
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"GroqProvider.complete_json unreachable: {exc}") from exc
        except Exception as exc:
            # openai/instructor raise their own APIConnectionError/APIStatusError subclasses
            # (not httpx.HTTPError) for network and auth failures against the Groq endpoint.
            if type(exc).__module__.startswith("openai"):
                raise LLMUnavailableError(f"GroqProvider.complete_json failed: {exc}") from exc
            raise

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Groq does not provide an embedding API; callers must fall back to local."""
        raise NotImplementedError(
            "GroqProvider does not support embeddings. "
            "Use LocalProvider or OpenAIProvider for embed()."
        )
