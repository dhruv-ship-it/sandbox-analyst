"""The real sandbox backend: a fresh, network-isolated Modal Sandbox per run.

A sandbox exists only for the duration of `run()` — it is created,
used, and terminated within a single call. Nothing stays alive while
the LLM is "thinking" between attempts.
"""

import contextlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

import modal
from modal.types import FileType

from .base import (
    OUTPUT_DIR,
    UPLOAD_DIR,
    WORKDIR,
    ExecError,
    ExecResult,
    SandboxCrashed,
    SandboxUnavailable,
    cap_exec_result,
    validate_upload_name,
    validate_upload_size,
)
from .ledger import DEFAULT_LEDGER_PATH, append_entry, check_budget, make_entry
from .modal_image import RUNNER_PATH, build_image

if TYPE_CHECKING:
    from sandbox_analyst.config import Settings

APP_NAME = "sandbox-analyst"
TASK_PATH = f"{WORKDIR}/task.py"
ERROR_PATH = f"{WORKDIR}/error.json"

# modal.Sandbox.exec's timeout is implemented by Modal setting returncode to
# this sentinel rather than raising, when the exec session's own timeout
# elapses (see docs/sandbox-env.md for the source reference that confirms
# this -- it's an internal Modal behavior, not public API, so it's isolated
# here in one place).
EXEC_TIMEOUT_RETURNCODE = -1


class ModalSandbox:
    """A Sandbox backed by a real Modal Sandbox (gVisor, no network)."""

    backend = "modal"

    def __init__(self, settings: "Settings", ledger_path: Path | None = None) -> None:
        self._settings = settings
        self._uploads: dict[str, bytes] = {}
        self._ledger_path = ledger_path or DEFAULT_LEDGER_PATH
        self.last_run_cost_usd = 0.0

    def __enter__(self) -> "ModalSandbox":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def upload(self, name: str, data: bytes) -> str:
        validate_upload_name(name)
        validate_upload_size(len(data), self._settings.max_upload_mb)
        self._uploads[name] = data
        return f"{UPLOAD_DIR}/{name}"

    def run(self, code: str, timeout_s: int | None = None) -> ExecResult:
        check_budget(self._ledger_path, self._settings.sa_sandbox_budget_usd)
        run_timeout = timeout_s or self._settings.run_timeout_s

        app = modal.App.lookup(APP_NAME, create_if_missing=True)
        image = build_image()

        lifetime_start = time.monotonic()
        try:
            sandbox = modal.Sandbox.create(
                "sleep",
                str(self._settings.sandbox_lifetime_s),
                app=app,
                image=image,
                block_network=True,
                timeout=self._settings.sandbox_lifetime_s,
                cpu=self._settings.sandbox_cpu,
                memory=(
                    self._settings.sandbox_memory_mib,
                    self._settings.sandbox_memory_hard_limit_mib,
                ),
                workdir=WORKDIR,
            )
        except modal.exception.Error as exc:
            raise SandboxUnavailable(f"could not create Modal sandbox: {exc}") from exc

        try:
            result = self._exec_task(sandbox, code, run_timeout)
        except modal.exception.Error as exc:
            raise SandboxCrashed(f"Modal sandbox failed mid-run: {exc}") from exc
        finally:
            alive_s = time.monotonic() - lifetime_start
            with contextlib.suppress(modal.exception.Error):
                sandbox.terminate()
            self._record_ledger_entry(alive_s)

        return cap_exec_result(result)

    def _exec_task(self, sandbox: "modal.Sandbox", code: str, timeout_s: int) -> ExecResult:
        for name, data in self._uploads.items():
            sandbox.filesystem.write_bytes(data, f"{UPLOAD_DIR}/{name}")
        sandbox.filesystem.write_text(code, TASK_PATH)

        exec_start = time.monotonic()
        process = sandbox.exec("python", RUNNER_PATH, timeout=timeout_s, workdir=WORKDIR)
        stdout = process.stdout.read()
        stderr = process.stderr.read()
        exit_code = process.wait()
        duration_ms = int((time.monotonic() - exec_start) * 1000)

        timed_out = exit_code == EXEC_TIMEOUT_RETURNCODE
        error = None if timed_out else self._read_error(sandbox)
        images = self._read_images(sandbox)

        return ExecResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=None if timed_out else exit_code,
            error=error,
            images=images,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=False,
        )

    def _read_error(self, sandbox: "modal.Sandbox") -> ExecError | None:
        try:
            raw = sandbox.filesystem.read_text(ERROR_PATH)
        except modal.exception.SandboxFilesystemNotFoundError:
            return None
        data = json.loads(raw)
        return ExecError(name=data["name"], value=data["value"], traceback=data["traceback"])

    def _read_images(self, sandbox: "modal.Sandbox") -> list[bytes]:
        try:
            entries = sandbox.filesystem.list_files(OUTPUT_DIR)
        except modal.exception.SandboxFilesystemNotFoundError:
            return []
        png_paths = sorted(
            entry.path
            for entry in entries
            if entry.type == FileType.FILE and entry.name.endswith(".png")
        )
        return [sandbox.filesystem.read_bytes(path) for path in png_paths]

    def _record_ledger_entry(self, alive_s: float) -> None:
        entry = make_entry(
            alive_s=alive_s,
            cpu=self._settings.sandbox_cpu,
            memory_gib=self._settings.sandbox_memory_mib / 1024,
            usd_per_core_second=self._settings.usd_per_core_second,
            usd_per_gib_second=self._settings.usd_per_gib_second,
        )
        append_entry(self._ledger_path, entry)
        self.last_run_cost_usd = entry.est_usd

    def close(self) -> None:
        """No-op: every sandbox is already terminated at the end of run()."""
