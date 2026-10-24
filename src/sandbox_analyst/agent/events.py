"""The agent's event schema: one shared shape for JSONL traces and the future SSE stream.

An AgentEvent is intentionally plain (frozen dataclass, JSON-serializable
payload) so the exact same shape can be appended to a trace file now and
streamed over SSE later (P4) with no translation layer in between.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

EventType = Literal[
    "run_started",
    "profile",
    "llm_request",
    "llm_response",
    "code",
    "static_check",
    "exec_started",
    "exec_result",
    "answer",
    "evidence",
    "observation",
    "run_finished",
]

OnEvent = Callable[["AgentEvent"], None]


@dataclass(frozen=True)
class AgentEvent:
    run_id: str
    seq: int
    ts: float
    type: EventType
    attempt: int
    payload: dict[str, object]


def new_run_id() -> str:
    return uuid.uuid4().hex


class EventEmitter:
    """Assigns run_id/seq/ts to each event and forwards it to `on_event`.

    `on_event` is optional so callers that don't care about step-by-step
    events (e.g. a one-off smoke script) can pass None.
    """

    def __init__(self, run_id: str, on_event: OnEvent | None = None) -> None:
        self.run_id = run_id
        self._on_event = on_event
        self._seq = 0

    def emit(self, type: EventType, attempt: int, payload: dict[str, object]) -> AgentEvent:
        event = AgentEvent(
            run_id=self.run_id,
            seq=self._seq,
            ts=time.time(),
            type=type,
            attempt=attempt,
            payload=payload,
        )
        self._seq += 1
        if self._on_event is not None:
            self._on_event(event)
        return event
