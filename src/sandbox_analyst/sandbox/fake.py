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
    ) -> None:
        self._queue: deque[ExecResult | Exception] = deque(script or [])
        self._max_upload_mb = max_upload_mb
        self.uploads: dict[str, bytes] = {}
        self.runs: list[str] = []
        self.closed = False

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
            raise item
        return item

    def close(self) -> None:
        self.closed = True
