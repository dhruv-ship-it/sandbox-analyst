"""An LLMClient for any OpenAI-compatible chat completions endpoint.

Used for both NVIDIA NIM and Groq: same request/response shape, only the
base URL, API key, and per-provider rate limit differ. The `openai` SDK
is used purely as an HTTP client here (D-002) -- its own retry logic is
disabled (`max_retries=0`) in favor of this module's policy, which
retries only infrastructure failures (429, 5xx, timeouts, connection
errors) and raises immediately on anything else (D-037).
"""

import random
import time
from collections.abc import Callable
from pathlib import Path

import httpx2
import openai
from openai.types.chat import ChatCompletion

from .base import (
    LLMConfigError,
    LLMResponse,
    LLMTruncated,
    LLMUnavailable,
    Message,
    RateLimitExhausted,
)
from .limiter import RateLimiter
from .usage import DEFAULT_USAGE_LOG_PATH, append_usage, make_entry

PROVIDER_BASE_URLS = {
    "nim": "https://integrate.api.nvidia.com/v1",
    "groq": "https://api.groq.com/openai/v1",
}

MAX_ATTEMPTS = 6
BASE_BACKOFF_S = 1.0
MAX_BACKOFF_S = 30.0


def _retry_after_seconds(exc: openai.APIStatusError) -> float | None:
    value = exc.response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class OpenAICompatClient:
    """LLMClient backed by an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: str,
        rpm: float,
        timeout_s: float,
        default_temperature: float,
        default_top_p: float,
        default_max_tokens: int,
        default_reasoning_effort: str | None,
        usage_log_path: Path = DEFAULT_USAGE_LOG_PATH,
        sleep: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
        http_client: httpx2.Client | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self._default_temperature = default_temperature
        self._default_top_p = default_top_p
        self._default_max_tokens = default_max_tokens
        self._default_reasoning_effort = default_reasoning_effort
        self._usage_log_path = usage_log_path
        self._sleep = sleep
        self._random = random_fn
        self._limiter = RateLimiter(rpm=rpm, sleep=sleep)
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_s,
            max_retries=0,
            http_client=http_client,
        )

    def __repr__(self) -> str:
        # Deliberately no api_key field: it must never appear in a repr or log line.
        return f"OpenAICompatClient(provider={self.provider!r}, model={self.model!r})"

    def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens if max_tokens is not None else self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._default_temperature,
            "top_p": top_p if top_p is not None else self._default_top_p,
        }
        effort = (
            reasoning_effort if reasoning_effort is not None else self._default_reasoning_effort
        )
        if effort is not None:
            kwargs["reasoning_effort"] = effort

        attempt = 0
        while True:
            attempt += 1
            self._limiter.wait()
            start = time.monotonic()
            try:
                completion = self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:
                self._log_failure(start, "APITimeoutError")
                if attempt >= MAX_ATTEMPTS:
                    raise LLMUnavailable(
                        f"{self.provider}: request timed out after {attempt} attempts"
                    ) from exc
                self._backoff(attempt, retry_after=None)
                continue
            except openai.APIConnectionError as exc:
                self._log_failure(start, "APIConnectionError")
                if attempt >= MAX_ATTEMPTS:
                    raise LLMUnavailable(
                        f"{self.provider}: connection error after {attempt} attempts"
                    ) from exc
                self._backoff(attempt, retry_after=None)
                continue
            except openai.APIStatusError as exc:
                status = exc.status_code
                self._log_failure(start, type(exc).__name__)
                if status == 429:
                    if attempt >= MAX_ATTEMPTS:
                        raise RateLimitExhausted(
                            f"{self.provider}: rate limited after {attempt} attempts"
                        ) from exc
                    self._backoff(attempt, retry_after=_retry_after_seconds(exc))
                    continue
                if status >= 500:
                    if attempt >= MAX_ATTEMPTS:
                        raise LLMUnavailable(
                            f"{self.provider}: HTTP {status} after {attempt} attempts"
                        ) from exc
                    self._backoff(attempt, retry_after=_retry_after_seconds(exc))
                    continue
                raise LLMConfigError(f"{self.provider} ({status}): {exc.message}") from exc

            return self._to_response(completion, start)

    def _to_response(self, completion: ChatCompletion, start: float) -> LLMResponse:
        latency_ms = int((time.monotonic() - start) * 1000)
        choice = completion.choices[0]
        message = choice.message
        text = message.content or ""
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        usage = completion.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        self._log_success(latency_ms, prompt_tokens, completion_tokens, choice.finish_reason)

        if choice.finish_reason == "length" and not text:
            raise LLMTruncated(
                f"{self.provider}/{self.model}: hit max_tokens with no visible content "
                f"(completion_tokens={completion_tokens}, all spent on reasoning)"
            )

        return LLMResponse(
            text=text,
            reasoning=reasoning,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            provider=self.provider,
            model=self.model,
            finish_reason=choice.finish_reason,
        )

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None:
            self._sleep(retry_after)
            return
        cap = min(BASE_BACKOFF_S * (2 ** (attempt - 1)), MAX_BACKOFF_S)
        self._sleep(cap * self._random())

    def _log_success(
        self,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        finish_reason: str,
    ) -> None:
        append_usage(
            make_entry(
                provider=self.provider,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
                ok=True,
            ),
            path=self._usage_log_path,
        )

    def _log_failure(self, start: float, error_type: str) -> None:
        latency_ms = int((time.monotonic() - start) * 1000)
        append_usage(
            make_entry(
                provider=self.provider,
                model=self.model,
                latency_ms=latency_ms,
                ok=False,
                error_type=error_type,
            ),
            path=self._usage_log_path,
        )
