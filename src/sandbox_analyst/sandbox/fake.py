"""An in-memory sandbox that never executes anything.

Used by unit tests and offline development so agent-loop logic can be
exercised without Modal, a network, or real code execution.
"""

from collections import deque
from collections.abc import Iterable

from .base import (
    UPLOAD_DIR,
    ExecResult,
    SandboxUnavailable,
    validate_upload_name,
    validate_upload_size,
)


class FakeSandbox:
    """A scripted stand-in for a real sandbox.

    Construct with a queue of `ExecResult` (returned) or `Exception`
    (raised) objects; each call to `run()` consumes the next item. It
    never parses, compiles, or executes the `code` it's given — it only
    records it.
    """

    backend = "fake"

    def __init__(
        self,
        script: Iterable[ExecResult | Exception] | None = None,
        max_upload_mb: int = 25,
        run_cost_usd: float = 0.0,
    ) -> None:
        self._queue: deque[ExecResult | Exception] = deque(script or [])
        self._max_upload_mb = max_upload_mb
        self._run_cost_usd = run_cost_usd
        self.uploads: dict[str, bytes] = {}
        self.runs: list[str] = []
        self.closed = False
        self.last_run_cost_usd = 0.0

    def __enter__(self) -> "FakeSandbox":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def upload(self, name: str, data: bytes) -> str:
        validate_upload_name(name)
        validate_upload_size(len(data), self._max_upload_mb)
        self.uploads[name] = data
        return f"{UPLOAD_DIR}/{name}"

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        self.runs.append(code)
        if not self._queue:
            raise SandboxUnavailable("FakeSandbox's scripted result queue is exhausted")
        item = self._queue.popleft()
        if isinstance(item, Exception):
            if not isinstance(item, SandboxUnavailable):
                # A real sandbox was created and billed even though this run failed.
                self.last_run_cost_usd = self._run_cost_usd
            raise item
        self.last_run_cost_usd = self._run_cost_usd
        return item

    def close(self) -> None:
        self.closed = True
