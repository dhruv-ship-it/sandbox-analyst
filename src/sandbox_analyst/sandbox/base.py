"""Shared types, exceptions, constants, and host-side helpers for sandboxes.

This module defines the contract every sandbox backend (FakeSandbox,
ModalSandbox) implements. It never executes any code itself.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

WORKDIR = "/work"
UPLOAD_DIR = f"{WORKDIR}/data"
OUTPUT_DIR = f"{WORKDIR}/out"

# Host-side output caps, applied to every real sandbox run before the
# result is handed to the agent.
MAX_TEXT_CHARS = 20_000
MAX_TEXT_KEEP_CHARS = 10_000
TRUNCATION_MARKER = "\n...[truncated]...\n"
MAX_TRACEBACK_LINES = 30
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ExecError:
    """A Python exception raised by user code, captured structurally."""

    name: str
    value: str
    traceback: str


@dataclass(frozen=True)
class ExecResult:
    """The result of running one script in a sandbox.

    A Python exception or timeout *inside user code* is represented here
    (via `error` / `timed_out`), not raised as a host-side exception, so
    the agent can observe it and repair its script.
    """

    stdout: str
    stderr: str
    exit_code: int | None
    error: ExecError | None
    images: list[bytes]
    duration_ms: int
    timed_out: bool
    truncated: bool


class SandboxError(Exception):
    """Base exception for sandbox-infrastructure failures."""


class SandboxUnavailable(SandboxError):
    """A sandbox could not be created: budget exhausted, provider API error."""


class SandboxCrashed(SandboxError):
    """A sandbox died mid-run, for reasons other than user-code behavior."""


@runtime_checkable
class Sandbox(Protocol):
    """The interface every sandbox backend implements."""

    backend: str

    # The lifecycle cost (create + exec + terminate) actually recorded in
    # the sandbox ledger for the most recent `run()` call -- the single
    # source of truth for sandbox spend (D-054). Updated even when `run()`
    # raises SandboxCrashed (a sandbox was still created and billed), but
    # left unchanged when it raises SandboxUnavailable before a sandbox
    # was ever created.
    last_run_cost_usd: float

    def __enter__(self) -> "Sandbox": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def upload(self, name: str, data: bytes) -> str:
        """Upload a file, returning its remote path under UPLOAD_DIR."""
        ...

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        """Run `code` as a complete script in a fresh environment.

        No state carries over between calls; files uploaded earlier are
        available to every run.
        """
        ...

    def close(self) -> None: ...


def validate_upload_name(name: str) -> None:
    """Reject anything but a plain file name: no separators, no '..'."""
    if not name:
        raise ValueError("upload name must not be empty")
    if "/" in name or "\\" in name:
        raise ValueError(f"upload name must be a plain file name, not a path: {name!r}")
    if ".." in name:
        raise ValueError(f"upload name must not contain '..': {name!r}")


def validate_upload_size(size_bytes: int, max_upload_mb: int) -> None:
    max_bytes = max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValueError(
            f"upload too large: {size_bytes} bytes exceeds the {max_upload_mb} MB limit"
        )


def _cap_text(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    capped = text[:MAX_TEXT_KEEP_CHARS] + TRUNCATION_MARKER + text[-MAX_TEXT_KEEP_CHARS:]
    return capped, True


def _cap_traceback(traceback_text: str) -> tuple[str, bool]:
    lines = traceback_text.splitlines()
    if len(lines) <= MAX_TRACEBACK_LINES:
        return traceback_text, False
    return "\n".join(lines[-MAX_TRACEBACK_LINES:]), True


def _cap_images(images: list[bytes]) -> tuple[list[bytes], bool]:
    kept: list[bytes] = []
    truncated = False
    for image in images:
        if len(kept) >= MAX_IMAGES:
            truncated = True
            break
        if len(image) > MAX_IMAGE_BYTES:
            truncated = True
            continue
        kept.append(image)
    return kept, truncated


def cap_exec_result(result: ExecResult) -> ExecResult:
    """Apply the shared host-side output caps to a raw ExecResult.

    Real sandbox backends run this on everything they capture before
    returning it, so no single run can hand the agent an unbounded
    amount of stdout/stderr/traceback/image data.
    """
    stdout, stdout_truncated = _cap_text(result.stdout)
    stderr, stderr_truncated = _cap_text(result.stderr)

    error = result.error
    traceback_truncated = False
    if error is not None:
        capped_traceback, traceback_truncated = _cap_traceback(error.traceback)
        error = ExecError(name=error.name, value=error.value, traceback=capped_traceback)

    images, images_truncated = _cap_images(result.images)

    truncated = (
        result.truncated
        or stdout_truncated
        or stderr_truncated
        or traceback_truncated
        or images_truncated
    )

    return ExecResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=result.exit_code,
        error=error,
        images=images,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        truncated=truncated,
    )
