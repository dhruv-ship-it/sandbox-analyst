"""Fault-injecting wrappers around a Sandbox and an LLMClient.

Each wrapper delegates to a real `inner` backend (a `FakeLLM`/`FakeSandbox`
in unit tests, the real `OpenAICompatClient`/`ModalSandbox` in the live
red-team run) for every call EXCEPT the ones explicitly scheduled to
fail, which raise (or return a scripted bad response) without ever
reaching `inner` at all -- so the fault is deterministic and instant,
not dependent on a real service actually misbehaving at the right
moment.
"""

from collections import deque
from collections.abc import Iterable

from sandbox_analyst.llm import LLMClient, LLMResponse, Message
from sandbox_analyst.sandbox import ExecResult, Sandbox

FaultOrNone = Exception | LLMResponse | None


class FaultyLLM:
    """Wraps an LLMClient; a scheduled item replaces one `complete()` call."""

    def __init__(self, inner: LLMClient, schedule: Iterable[FaultOrNone]) -> None:
        self._inner = inner
        self._schedule: deque[FaultOrNone] = deque(schedule)
        self.provider = inner.provider
        self.model = inner.model
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], **kwargs: object) -> LLMResponse:
        self.calls.append(list(messages))
        item = self._schedule.popleft() if self._schedule else None
        if item is None:
            return self._inner.complete(messages, **kwargs)  # type: ignore[arg-type]
        if isinstance(item, Exception):
            raise item
        return item


class FaultySandbox:
    """Wraps a Sandbox; a scheduled item replaces one `run()` call."""

    def __init__(self, inner: Sandbox, schedule: Iterable[FaultOrNone]) -> None:
        self._inner = inner
        self._schedule: deque[FaultOrNone] = deque(schedule)
        self.backend = inner.backend
        self.last_run_cost_usd = 0.0

    def __enter__(self) -> "FaultySandbox":
        self._inner.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._inner.__exit__(exc_type, exc, tb)

    def upload(self, name: str, data: bytes) -> str:
        return self._inner.upload(name, data)

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        item = self._schedule.popleft() if self._schedule else None
        if item is None:
            result = self._inner.run(code, timeout_s=timeout_s)
            self.last_run_cost_usd = self._inner.last_run_cost_usd
            return result
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self._inner.close()
