"""Shared types and exceptions for the LLM layer.

Defines the contract every LLM client (OpenAICompatClient, FakeLLM,
RecordingLLM, ReplayLLM) implements. Mirrors sandbox/base.py's shape: a
plain frozen dataclass for host-constructed response data, a
runtime-checkable Protocol for the interface.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """One completed LLM call.

    `text` is the visible content only. `reasoning` holds a provider's
    separate reasoning/thinking output when it returns one (NIM/Groq
    expose this as `reasoning_content` or `reasoning` on the message;
    it is never mixed into `text`).
    """

    text: str
    reasoning: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    provider: str
    model: str
    finish_reason: str


class LLMError(Exception):
    """Base exception for LLM-layer failures."""


class RateLimitExhausted(LLMError):
    """A 429 response persisted through every retry attempt."""


class LLMUnavailable(LLMError):
    """A 5xx response, timeout, or connection error persisted through every retry attempt."""


class LLMConfigError(LLMError):
    """A non-retryable 4xx response (400/401/403/404/410/...): carries the provider's message."""


class LLMTruncated(LLMError):
    """finish_reason == "length" with no visible content: reasoning used the whole budget."""


@runtime_checkable
class LLMClient(Protocol):
    """The interface every LLM backend implements."""

    provider: str
    model: str

    def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse: ...
