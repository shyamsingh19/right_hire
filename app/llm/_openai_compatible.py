from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque

from pydantic import BaseModel

from app.llm.base import LLMProvider, LLMUnavailableError

logger = logging.getLogger(__name__)

_HEALTH_TIMEOUT = 5.0


class _RateLimiter:
    """Sliding-window throttle so we stay under a provider's requests-per-minute cap
    instead of finding out via 429s. Shared across all calls in this process (one RQ
    worker == one process handling candidates one at a time, so a process-local window
    is sufficient)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: deque[float] = deque()

    def wait(self, limit: int) -> None:
        limit = max(limit, 1)
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > 60.0:
                self._calls.popleft()
            if len(self._calls) >= limit:
                sleep_for = 60.0 - (now - self._calls[0])
                if sleep_for > 0:
                    logger.info(
                        "%s throttling — at %d/%d requests this minute, waiting %.1fs",
                        type(self).__name__,
                        len(self._calls),
                        limit,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                now = time.monotonic()
                while self._calls and now - self._calls[0] > 60.0:
                    self._calls.popleft()
            self._calls.append(time.monotonic())


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


class OpenAICompatibleProvider(LLMProvider):
    """Base for LLM backends exposing an OpenAI-compatible /chat/completions API
    (Groq, Cerebras, ...). Handles client-side rate limiting, retry/backoff on
    transient failure, instructor-based structured output, and a raw-httpx fallback
    when instructor/openai aren't installed."""

    base_url: str
    provider_name: str
    _rate_limiter: _RateLimiter

    def __init__(
        self,
        model: str,
        api_key: str,
        requests_per_minute: int,
        max_retries: int,
        retry_backoff_base: float,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.requests_per_minute = requests_per_minute
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        if not self.api_key:
            raise LLMUnavailableError(
                f"{self.provider_name.upper()}_API_KEY is not set — "
                f"LLM_BACKEND={self.provider_name.lower()} requires it"
            )

    def health_check(self) -> None:
        """Probe the provider's /models — validates both reachability and the API key."""
        import httpx

        with httpx.Client(timeout=_HEALTH_TIMEOUT) as client:
            resp = client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()

    # Name of the instructor.Mode used to coax structured output out of the endpoint.
    # "JSON" (prompt the model, parse the reply) is the portable default, but it is only
    # as reliable as the model's instruction-following: gemma-4-31b on Cerebras never
    # terminates under it and burns the whole max_tokens budget. Providers whose endpoint
    # enforces the schema server-side should override with "JSON_SCHEMA" — see
    # app/llm/cerebras.py. Held as a name, not the enum, so instructor stays a lazy import.
    instructor_mode = "JSON"

    def _extra_create_kwargs(self) -> dict:
        """Hook for provider-specific chat-completion kwargs (e.g. reasoning_effort)."""
        return {}

    def complete_json(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_tokens: int = 256,
    ) -> BaseModel:
        """Call the provider via instructor with structured output, throttled to stay
        under the configured requests-per-minute cap and retried with backoff on
        transient failure."""
        max_retries = max(self.max_retries, 1)
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            self._rate_limiter.wait(self.requests_per_minute)
            try:
                return self._complete_json_once(prompt, schema, max_tokens)
            except LLMUnavailableError as exc:
                last_exc = exc
                logger.warning(
                    "%s.complete_json attempt %d/%d failed [model=%s]: %s",
                    type(self).__name__,
                    attempt,
                    max_retries,
                    self.model,
                    exc,
                )
                if attempt < max_retries:
                    retry_after = _retry_after_seconds(exc.__cause__) if exc.__cause__ else None
                    delay = retry_after or self.retry_backoff_base**attempt
                    time.sleep(delay)

        raise LLMUnavailableError(
            f"{type(self).__name__}.complete_json failed after {max_retries} attempts "
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
                        base_url=self.base_url,
                        timeout=60.0,
                    ),
                    mode=getattr(instructor.Mode, self.instructor_mode),
                )
                result, completion = client.chat.completions.create_with_completion(
                    model=self.model,
                    max_tokens=max_tokens,
                    response_model=schema,
                    messages=[{"role": "user", "content": prompt}],
                    **self._extra_create_kwargs(),
                )
                usage = completion.usage
                logger.info(
                    "%s.complete_json tokens — model=%s prompt=%d completion=%d total=%d",
                    type(self).__name__,
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
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    logger.info(
                        "%s.complete_json tokens (raw) — model=%s prompt=%s completion=%s total=%s",
                        type(self).__name__,
                        self.model,
                        usage.get("prompt_tokens"),
                        usage.get("completion_tokens"),
                        usage.get("total_tokens"),
                    )
                    return schema.model_validate(json.loads(content))
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"{type(self).__name__}.complete_json unreachable: {exc}"
            ) from exc
        except Exception as exc:
            # openai/instructor raise their own APIConnectionError/APIStatusError subclasses
            # (not httpx.HTTPError) for network and auth failures against the endpoint.
            if type(exc).__module__.startswith("openai"):
                raise LLMUnavailableError(
                    f"{type(self).__name__}.complete_json failed: {exc}"
                ) from exc
            raise

    def embed(self, texts: list[str]) -> list[list[float]]:
        """No embedding API; callers must fall back to LocalProvider or OpenAIProvider."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support embeddings. "
            "Use LocalProvider or OpenAIProvider for embed()."
        )
