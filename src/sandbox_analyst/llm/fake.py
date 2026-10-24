"""FakeLLM: a scripted LLMClient for offline tests and development, no network.

Mirrors sandbox/fake.py's FakeSandbox: a deque of scripted outcomes
(or a callable), with every call recorded.
"""

from collections import deque
from collections.abc import Callable, Iterable

from .base import LLMResponse, Message

RespondFn = Callable[..., LLMResponse]


def _estimate_tokens(n_chars: int) -> int:
    """~4 chars per token (see docs/llm.md); never zero, so an empty string still costs 1."""
    return max(1, n_chars // 4)


class FakeLLM:
    """A scripted stand-in for a real LLMClient.

    Construct with a queue of `str` (wrapped into a plausible
    `LLMResponse`), `LLMResponse` (returned as-is), or `Exception`
    (raised) items; each call to `complete()` consumes the next one.
    A `respond` callable overrides the queue entirely, for tests that
    need the response to depend on the request.
    """

    def __init__(
        self,
        script: Iterable[str | LLMResponse | Exception] | None = None,
        respond: RespondFn | None = None,
        provider: str = "fake",
        model: str = "fake-model",
    ) -> None:
        self._queue: deque[str | LLMResponse | Exception] = deque(script or [])
        self._respond = respond
        self.provider = provider
        self.model = model
        self.calls: list[dict] = []

    def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "reasoning_effort": reasoning_effort,
            }
        )
        if self._respond is not None:
            return self._respond(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                reasoning_effort=reasoning_effort,
            )
        if not self._queue:
            raise RuntimeError("FakeLLM's scripted response queue is exhausted")
        item = self._queue.popleft()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            prompt_chars = sum(len(m.content) for m in messages)
            return LLMResponse(
                text=item,
                reasoning=None,
                prompt_tokens=_estimate_tokens(prompt_chars),
                completion_tokens=_estimate_tokens(len(item)),
                latency_ms=0,
                provider=self.provider,
                model=self.model,
                finish_reason="stop",
            )
        return item
