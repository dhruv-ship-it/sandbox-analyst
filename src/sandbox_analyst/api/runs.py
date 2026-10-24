"""The in-memory run store: starts a background agent run, fans its events out to SSE
subscribers, and keeps a snapshot for the result/trace endpoints.

Single-process, single-worker design (see DECISIONS.md D-073) -- a plain
`dict[str, RunRecord]`, no database. `run_agent` (agent/loop.py) is called
exactly as the CLI calls it; nothing here edits agent-loop behavior
(CLAUDE.md rule 9 for this task). Because `run_agent` always mints its own
internal run id (D-053) and `_write_artifacts` hardcodes its own directory
(see D-067), this module mints its OWN public run id up front and only
borrows the agent's internal id, once known, to locate chart PNGs.
"""

import asyncio
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sandbox_analyst.agent import AgentEvent, AgentResult, AttemptRecord, TraceWriter, run_agent
from sandbox_analyst.agent import loop as agent_loop
from sandbox_analyst.llm import LLMClient
from sandbox_analyst.sandbox import Sandbox

from .limits import RateLimiter

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

# Matches exactly what agent/loop.py's _write_artifacts ever generates.
ARTIFACT_NAME_RE = re.compile(r"^attempt\d+_\d+\.png$")

#: Statuses that mean the run will never emit another event.
TERMINAL_STATUSES = frozenset(
    {
        "answered",
        "failed",
        "repeated_failure",
        "tool_failure",
        "budget_exceeded",
        "llm_error",
        "error",
    }
)

STDOUT_TAIL_CHARS = 2000
OBSERVATION_PREVIEW_CHARS = 300

# Internal sentinel pushed to every subscriber queue once a run can emit no
# more events (whether it finished cleanly or raised unexpectedly), so an
# SSE connection waiting on an empty queue is guaranteed to wake up and close.
_CLOSE_SENTINEL = {"type": "__closed__"}


@dataclass
class RunRecord:
    run_id: str
    dataset_id: str
    question: str
    client_ip: str
    created_at: float
    status: str = "pending"
    agent_run_id: str | None = None
    events: list[dict] = field(default_factory=list)
    result: AgentResult | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: list[asyncio.Queue] = field(default_factory=list)

    def subscribe(self) -> tuple[list[dict], asyncio.Queue]:
        """Atomically snapshot past events and register a queue for future ones."""
        queue: asyncio.Queue = asyncio.Queue()
        with self.lock:
            snapshot = list(self.events)
            self.subscribers.append(queue)
        return snapshot, queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self.lock:
            if queue in self.subscribers:
                self.subscribers.remove(queue)


def _event_to_dict(public_run_id: str, event: AgentEvent) -> dict:
    return {
        "run_id": public_run_id,
        "seq": event.seq,
        "ts": event.ts,
        "type": event.type,
        "attempt": event.attempt,
        "payload": event.payload,
    }


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def summarize_attempt(a: AttemptRecord) -> dict:
    exec_ok = None
    timed_out = None
    if a.exec_result is not None:
        exec_ok = a.exec_result.error is None and not a.exec_result.timed_out
        timed_out = a.exec_result.timed_out
    return {
        "attempt": a.attempt,
        "has_code": a.code is not None,
        "check_ok": a.check_ok,
        "n_check_violations": len(a.check_violations),
        "exec_ok": exec_ok,
        "timed_out": timed_out,
        "answered": a.answer is not None,
        "observation": _truncate(a.observation, OBSERVATION_PREVIEW_CHARS),
    }


def chart_urls(run_id: str, result: AgentResult) -> list[str]:
    return [f"/api/runs/{run_id}/artifacts/{Path(p).name}" for p in result.images]


def build_summary(record: RunRecord) -> dict:
    """The current snapshot of a run -- complete once `record.result` is set."""
    with record.lock:
        status = record.status
        result = record.result
        error = record.error

    base = {
        "run_id": record.run_id,
        "dataset_id": record.dataset_id,
        "question": record.question,
        "status": status,
        "answers": [],
        "explanation": "",
        "code": "",
        "stdout_tail": "",
        "evidence": [],
        "attempts": [],
        "chart_urls": [],
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_ms": 0,
        "error": error,
    }
    if result is None:
        return base

    base.update(
        {
            "answers": [{"name": a.name, "value": a.value} for a in result.answers],
            "explanation": result.explanation,
            "code": result.code,
            "stdout_tail": _truncate(result.stdout, STDOUT_TAIL_CHARS) or "",
            "evidence": [
                {"name": e.name, "value": e.value, "passed": e.passed, "reason": e.reason}
                for e in result.evidence
            ],
            "attempts": [summarize_attempt(a) for a in result.attempts],
            "chart_urls": chart_urls(record.run_id, result),
            "prompt_tokens": result.total_prompt_tokens,
            "completion_tokens": result.total_completion_tokens,
            "latency_ms": result.total_latency_ms,
        }
    )
    return base


def artifact_path(record: RunRecord, name: str) -> Path | None:
    """The validated, on-disk path for chart `name`, or None if it can't be served.

    `name` must match the agent's own PNG naming scheme exactly (defense in
    depth against path traversal, see D-075); the resolved path is also
    checked to actually live inside the expected run artifact directory.
    """
    with record.lock:
        agent_run_id = record.agent_run_id
    if agent_run_id is None or not ARTIFACT_NAME_RE.match(name):
        return None
    run_dir = (agent_loop.DEFAULT_ARTIFACTS_DIR / agent_run_id).resolve()
    candidate = (run_dir / name).resolve()
    if candidate.parent != run_dir or not candidate.is_file():
        return None
    return candidate


class RunStore:
    """Creates runs, executes them in a background thread pool, fans out events."""

    def __init__(self, max_workers: int) -> None:
        self._records: dict[str, RunRecord] = {}
        self._store_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sa-run")

    def get(self, run_id: str) -> RunRecord | None:
        with self._store_lock:
            return self._records.get(run_id)

    def start(
        self,
        *,
        dataset_id: str,
        question: str,
        client_ip: str,
        csv_bytes: bytes,
        file_name: str,
        llm: LLMClient,
        sandbox_factory: Callable[[], Sandbox],
        settings: "Settings",
        trace_dir: Path,
        loop: asyncio.AbstractEventLoop,
        limiter: RateLimiter,
    ) -> RunRecord:
        """Create a RunRecord and submit its execution to the thread pool.

        The caller is responsible for having already called
        `limiter.reserve()` successfully; this method's background job
        calls `limiter.release()` exactly once, when the run ends.
        """
        record = RunRecord(
            run_id=uuid.uuid4().hex,
            dataset_id=dataset_id,
            question=question,
            client_ip=client_ip,
            created_at=time.time(),
        )
        with self._store_lock:
            self._records[record.run_id] = record

        self._executor.submit(
            _execute_run,
            record,
            csv_bytes=csv_bytes,
            file_name=file_name,
            llm=llm,
            sandbox_factory=sandbox_factory,
            settings=settings,
            trace_dir=trace_dir,
            loop=loop,
            limiter=limiter,
        )
        return record


def _execute_run(
    record: RunRecord,
    *,
    csv_bytes: bytes,
    file_name: str,
    llm: LLMClient,
    sandbox_factory: Callable[[], Sandbox],
    settings: "Settings",
    trace_dir: Path,
    loop: asyncio.AbstractEventLoop,
    limiter: RateLimiter,
) -> None:
    """Runs in a worker thread. Calls run_agent and fans events out live."""
    with record.lock:
        record.status = "running"
    trace_writer = TraceWriter(record.run_id, trace_dir=trace_dir)

    def on_event(event: AgentEvent) -> None:
        with record.lock:
            if record.agent_run_id is None:
                record.agent_run_id = event.run_id
            event_dict = _event_to_dict(record.run_id, event)
            record.events.append(event_dict)
            subscribers = list(record.subscribers)
        trace_writer(event)
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, event_dict)

    try:
        result = run_agent(
            csv_bytes,
            file_name,
            record.question,
            llm=llm,
            sandbox_factory=sandbox_factory,
            settings=settings,
            on_event=on_event,
        )
        with record.lock:
            record.result = result
            record.status = result.status
    except Exception as exc:  # an unexpected failure outside run_agent's own status machine
        with record.lock:
            record.status = "error"
            record.error = str(exc)
            next_seq = len(record.events)
            fallback_run_id = record.agent_run_id or record.run_id
        # run_agent's own "run_finished" event is what tells an SSE client (and the
        # trace file) that a run is over; an unexpected failure here happens outside
        # run_agent's own event emission entirely, so without this, a live client has
        # no event-level signal to stop on -- only the connection silently closing,
        # which EventSource would just keep reconnecting against (see DECISIONS.md).
        on_event(
            AgentEvent(
                run_id=fallback_run_id,
                seq=next_seq,
                ts=time.time(),
                type="run_finished",
                attempt=agent_loop.MAX_ATTEMPTS,
                payload={
                    "status": "error",
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_latency_ms": 0,
                    "sandbox_usd": 0.0,
                },
            )
        )
    finally:
        limiter.release()
        with record.lock:
            subscribers = list(record.subscribers)
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, _CLOSE_SENTINEL)
