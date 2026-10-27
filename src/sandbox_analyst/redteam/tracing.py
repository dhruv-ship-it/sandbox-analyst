"""A lazy on_event subscriber that writes a trace, keyed by the run's own run_id.

Mirrors `bench.harness._LazyTraceAndCollect` and `cli._LazyTraceWriter` (D-053:
the run_id is assigned inside `run_agent` itself, not generated up front, so
the `TraceWriter` can only be constructed once the first event arrives).
Shared here across the redteam categories rather than duplicated per module,
since all three live in this one package.
"""

from sandbox_analyst.agent import AgentEvent, TraceWriter


class LazyTraceWriter:
    """Writes every event it receives to one trace file; `.path` is "" until the first event."""

    def __init__(self) -> None:
        self._writer: TraceWriter | None = None

    @property
    def path(self) -> str:
        return str(self._writer.path) if self._writer is not None else ""

    def __call__(self, event: AgentEvent) -> None:
        if self._writer is None:
            self._writer = TraceWriter(event.run_id)
        self._writer(event)
